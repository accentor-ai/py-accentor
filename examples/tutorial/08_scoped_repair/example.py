"""Tutorial 08: Scoped Repair — exception-triggered agentic recovery.

Part 1: StageRepairPolicy — the on_error declaration, required fields,
        exception matching, and how policies are normalized.
Part 2: Repair lifecycle — what happens when a stage raises a declared
        exception: incident capture, workspace staging, agent dispatch,
        diff-scope verdict, rerun, and validation.
Part 3: DiffScopeVerdict and FileChange — evaluating whether repair edits
        stayed inside the declared editable scope.
Part 4: MockAgent and repair boundaries — why MockAgent always produces a
        repair.unsupported diagnostic, and what a real adapter would do.
Part 5: Repair events — the repair.recorded event lifecycle, reading
        repair metadata from result.events.
Part 6: Multiple exception types — routing different errors to different
        repair policies.
Part 7: What scoped repair won't do (by design).
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from accentor.core.decorators import stage, workflow
from accentor.core.decorators.stage import StageRepairPolicy, build_stage_config
from accentor.core.task.events import TaskEvent
from accentor.dispatch.agents.providers.mock import MockAgent
from accentor.dispatch.workspace.diff import (
    DiffScopeVerdict,
    FileChange,
    diff_workspaces,
    evaluate_diff_scope,
)
from accentor.evaluate.validation import JsonRequired


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

EXAMPLE_DIR = Path(tempfile.mkdtemp(prefix="accentor_tut08_"))
DATA_FILE = EXAMPLE_DIR / "orders.csv"
DATA_FILE.write_text(
    "order_id,amount,status\nA001,49.99,paid\nA002,19.50,pending\nA003,120.00,paid\n",
    encoding="utf-8",
)

EXPECTED_COLUMNS = {"order_id", "amount", "status"}


class ImportSchemaError(Exception):
    """Raised when CSV columns do not match the expected schema."""


class DataValidationError(Exception):
    """Raised when parsed rows contain invalid data."""


# ---------------------------------------------------------------------------
# Part 1: StageRepairPolicy — the on_error declaration
# ---------------------------------------------------------------------------

def part1_repair_policy() -> None:
    print("=" * 60)
    print("PART 1: StageRepairPolicy — the on_error declaration")
    print("=" * 60)

    repair_agent = MockAgent(responses=["repair output"])

    # build_stage_config normalizes the on_error dict into StageRepairPolicy.
    def parse_orders() -> list[dict]:
        return []

    config = build_stage_config(
        parse_orders,
        name="parse_orders",
        readable=[DATA_FILE],
        editable=[DATA_FILE],
        on_error={
            ImportSchemaError: {
                "response": "agent_repair",
                "agent": repair_agent,
                "goal": "Fix CSV parsing so the pipeline completes.",
                "validators": [JsonRequired(keys=["paid_count"])],
            }
        },
    )

    print(f"\n  Stage config name: {config.name}")
    print(f"  execution:         {config.execution}")
    print(f"  readable:          {[str(p) for p in config.readable]}")
    print(f"  editable:          {[str(p) for p in config.editable]}")
    print(f"  repair_policies:   {len(config.repair_policies)}")

    policy = config.repair_policies[0]
    print(f"\n  StageRepairPolicy:")
    print(f"    exception_type: {policy.exception_type.__name__}")
    print(f"    response:       {policy.response}")
    print(f"    goal:           {policy.goal}")
    print(f"    readable:       {[str(p) for p in policy.readable]}")
    print(f"    editable:       {[str(p) for p in policy.editable]}")
    print(f"    validators:     {len(policy.validators)}")

    # to_dict() for serialization.
    d = policy.to_dict()
    print(f"\n  to_dict() keys: {sorted(d.keys())}")
    print(f"    agent: {d['agent']}")
    print(f"    exception_type: {d['exception_type']}")

    # Required fields: response, agent, goal (or prompt), readable, editable, validators.
    print(f"\n  Required on_error fields:")
    print(f"    response:   'agent_repair' (only v1 value)")
    print(f"    agent:      any object with run(request) method")
    print(f"    goal:       string describing the repair objective")
    print(f"    readable:   paths the agent can read")
    print(f"    editable:   paths the agent can modify")
    print(f"    validators: validators to check repair success")

    # If readable/editable are not in the policy dict, they inherit from the stage.
    print(f"\n  Scope inheritance: policy.readable == stage.readable? "
          f"{policy.readable == config.readable}")


# ---------------------------------------------------------------------------
# Part 2: Repair lifecycle with a real workflow
# ---------------------------------------------------------------------------

def part2_lifecycle() -> None:
    print("\n" + "=" * 60)
    print("PART 2: Repair lifecycle — what happens on declared exception")
    print("=" * 60)

    repair_agent = MockAgent(
        responses=["Repair agent examined the file but MockAgent cannot edit files."],
        capabilities={"supports_files": True},
    )

    @stage(
        name="parse_orders",
        readable=[DATA_FILE],
        editable=[DATA_FILE],
        on_error={
            ImportSchemaError: {
                "response": "agent_repair",
                "agent": repair_agent,
                "goal": "Fix CSV so required columns are present.",
                "validators": [
                    JsonRequired(keys=["paid_count", "order_ids"]),
                ],
            }
        },
    )
    def parse_orders() -> list[dict[str, str]]:
        with DATA_FILE.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=".")  # wrong delimiter!
            columns = set(reader.fieldnames or [])
            missing = EXPECTED_COLUMNS - columns
            if missing:
                raise ImportSchemaError(
                    f"Missing columns: {sorted(missing)}; found={sorted(columns)}"
                )
            return list(reader)

    @stage(name="summarize_orders")
    def summarize_orders(rows: list[dict[str, str]]) -> dict:
        paid = [r for r in rows if r.get("status") == "paid"]
        return {
            "paid_count": len(paid),
            "order_ids": [r["order_id"] for r in paid],
            "total": sum(float(r["amount"]) for r in paid),
        }

    @workflow(name="repair_demo")
    def demo() -> dict:
        rows = parse_orders()
        return summarize_orders(rows)

    result = demo()

    print(f"\n  ok:            {result.ok}")
    print(f"  attempt_count: {result.attempt_count}")

    # With MockAgent, repair will fail because MockAgent can't edit files.
    # The lifecycle steps are still recorded as events:
    print(f"\n  Lifecycle events ({len(result.events)}):")
    for event in result.events:
        label = event.stage or event.workflow or ""
        extra = ""
        if event.event_type == "repair.recorded" and event.repair:
            status = event.status or "?"
            extra = f" status={status}"
        print(f"    {event.event_type}: {label}{extra}")

    print(f"\n  Diagnostics:")
    for d in result.diagnostics:
        print(f"    [{d.severity}] {d.code}: {d.message[:80]}")

    # The lifecycle:
    print(f"""
  Repair lifecycle (when a declared exception is raised):
    1. Exception caught -> matched to StageRepairPolicy
    2. Incident captured (exception details, traceback, scope)
    3. Workspace staged (readable/editable files copied)
    4. Before-snapshot taken for diff comparison
    5. Repair agent dispatched with prompt + workspace
    6. Agent completes -> diff-scope verdict computed
    7. If diff ok -> repaired stage re-run with patched files
    8. Re-run output validated against policy.validators
    9. Result: accepted or rejected with full diagnostics
""")


# ---------------------------------------------------------------------------
# Part 3: DiffScopeVerdict and FileChange
# ---------------------------------------------------------------------------

def part3_diff_scope() -> None:
    print("=" * 60)
    print("PART 3: DiffScopeVerdict — checking repair stayed in scope")
    print("=" * 60)

    # Create two workspace snapshots: before and after repair.
    before_dir = Path(tempfile.mkdtemp(prefix="accentor_tut08_before_"))
    after_dir = Path(tempfile.mkdtemp(prefix="accentor_tut08_after_"))

    try:
        # Before: original CSV with wrong delimiter.
        (before_dir / "orders.csv").write_text(
            "order_id.amount.status\nA001.49.99.paid\n"
        )
        (before_dir / "config.json").write_text('{"delimiter": "."}')

        # After: agent fixed the CSV.
        (after_dir / "orders.csv").write_text(
            "order_id,amount,status\nA001,49.99,paid\n"
        )
        # Agent also changed config.json (this file).
        (after_dir / "config.json").write_text('{"delimiter": ","}')

        # Only orders.csv is declared editable.
        report = diff_workspaces(
            before_dir, after_dir, editable=["orders.csv"]
        )
        verdict = report.verdict

        print(f"\n  DiffScopeVerdict:")
        print(f"    ok:              {verdict.ok}")
        print(f"    editable_paths:  {list(verdict.editable_paths)}")
        print(f"    changed_paths:   {list(verdict.changed_paths)}")
        print(f"    violating_paths: {list(verdict.violating_paths)}")
        print(f"    modified_paths:  {list(verdict.modified_paths)}")

        # config.json was changed but not declared editable -> violation!
        print(f"\n  Violation: config.json changed but not in editable scope")

        # Each change is a FileChange record.
        print(f"\n  FileChange records:")
        for change in verdict.changes:
            print(f"    path:   {change.path}")
            print(f"    status: {change.status}")
            print(f"    in_scope: {change.inside_editable_scope}")
            if change.before_sha256:
                print(f"    before_sha256: {change.before_sha256[:16]}...")
            if change.after_sha256:
                print(f"    after_sha256:  {change.after_sha256[:16]}...")
            print()

        # Patch text is best-effort unified diff.
        if report.patch_text:
            print(f"  Patch text (first 200 chars):")
            print(f"    {report.patch_text[:200]}")

        # to_dict() for JSON serialization.
        d = verdict.to_dict()
        print(f"  to_dict() keys: {sorted(d.keys())}")

        # evaluate_diff_scope returns just the verdict (no patch text).
        verdict_only = evaluate_diff_scope(
            before_dir, after_dir, editable=["orders.csv"]
        )
        print(f"\n  evaluate_diff_scope().ok: {verdict_only.ok}")

        # Now test with both files editable — should pass.
        report2 = diff_workspaces(
            before_dir, after_dir, editable=["orders.csv", "config.json"]
        )
        print(f"\n  Both files editable:")
        print(f"    ok:              {report2.verdict.ok}")
        print(f"    violating_paths: {list(report2.verdict.violating_paths)}")

        # Added files: create a new file in after.
        (after_dir / "notes.txt").write_text("Repair notes.")
        report3 = diff_workspaces(
            before_dir, after_dir, editable=["orders.csv", "config.json"]
        )
        print(f"\n  New file added (not editable):")
        print(f"    ok:              {report3.verdict.ok}")
        print(f"    added_paths:     {list(report3.verdict.added_paths)}")
        print(f"    violating_paths: {list(report3.verdict.violating_paths)}")

    finally:
        shutil.rmtree(before_dir, ignore_errors=True)
        shutil.rmtree(after_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Part 4: MockAgent and repair boundaries
# ---------------------------------------------------------------------------

def part4_mock_agent_limits() -> None:
    print("\n" + "=" * 60)
    print("PART 4: MockAgent and repair — why it fails (by design)")
    print("=" * 60)

    # MockAgent with default capabilities cannot edit files.
    default_agent = MockAgent(responses=["some output"])
    can_repair = hasattr(default_agent, "supports_repair") and default_agent.supports_repair
    print(f"\n  MockAgent (default):")
    print(f"    supports_repair: {can_repair}")
    print(f"    -> Repair dispatches produce 'repair.unsupported' diagnostic")

    # MockAgent with supports_files=True can receive workspace, but won't
    # actually modify files — it returns scripted text.
    file_agent = MockAgent(
        responses=["I see the CSV file."],
        capabilities={"supports_files": True},
    )
    print(f"\n  MockAgent (supports_files=True):")
    print(f"    capabilities: {file_agent.capabilities.to_dict()}")
    print(f"    -> Repair agent dispatches, but no files change")
    print(f"    -> Result: 'repair.no_changes' diagnostic")

    # What a real adapter (e.g., CodexCli) would do:
    print(f"""
  Real repair agent behavior:
    1. Receives AgentRequest with workspace (StagedWorkspace)
    2. Reads files from workspace.readable paths
    3. Edits files at workspace.editable paths
    4. Returns AgentRunResult(ok=True, output="description of changes")
    5. Accentor computes diff-scope verdict on the workspace
    6. If in-scope: re-runs the repaired stage
    7. If out-of-scope: rejects with 'repair.diff_scope_violation'
""")


# ---------------------------------------------------------------------------
# Part 5: Repair events
# ---------------------------------------------------------------------------

def part5_repair_events() -> None:
    print("=" * 60)
    print("PART 5: Repair events — the repair.recorded lifecycle")
    print("=" * 60)

    # Construct repair events directly to show the event shape.
    e1 = TaskEvent.repair_recorded(
        repair={
            "stage": "parse_orders",
            "exception_type": "ImportSchemaError",
            "response": "agent_repair",
            "incident_artifact": "incident.json",
            "readable": [str(DATA_FILE)],
            "editable": [str(DATA_FILE)],
        },
        stage="parse_orders",
        status="incident_captured",
    )
    print(f"\n  repair.recorded (incident_captured):")
    print(f"    event_type: {e1.event_type}")
    print(f"    status:     {e1.status}")
    print(f"    repair keys: {sorted(e1.repair.keys())}")

    e2 = TaskEvent.repair_recorded(
        repair={
            "stage": "parse_orders",
            "agent": "CodexCli",
            "workspace_root": "/tmp/accentor-repair-xyz",
        },
        stage="parse_orders",
        status="repair_started",
    )
    print(f"\n  repair.recorded (repair_started):")
    print(f"    status: {e2.status}")
    print(f"    agent:  {e2.repair.get('agent')}")

    e3 = TaskEvent.repair_recorded(
        repair={
            "stage": "parse_orders",
            "diff_scope_ok": True,
            "changed_paths": ["orders.csv"],
            "violating_paths": [],
        },
        stage="parse_orders",
        status="diff_scope_checked",
    )
    print(f"\n  repair.recorded (diff_scope_checked):")
    print(f"    diff_scope_ok:  {e3.repair.get('diff_scope_ok')}")
    print(f"    changed_paths:  {e3.repair.get('changed_paths')}")

    e4 = TaskEvent.repair_recorded(
        repair={
            "stage": "parse_orders",
            "validation_ok": True,
            "changed_paths": ["orders.csv"],
        },
        stage="parse_orders",
        status="accepted",
    )
    print(f"\n  repair.recorded (accepted):")
    print(f"    status:        {e4.status}")
    print(f"    validation_ok: {e4.repair.get('validation_ok')}")

    # Rejected example.
    e5 = TaskEvent.repair_recorded(
        repair={
            "stage": "parse_orders",
            "code": "repair.diff_scope_violation",
            "violating_paths": ["config.json"],
        },
        stage="parse_orders",
        status="rejected",
    )
    print(f"\n  repair.recorded (rejected):")
    print(f"    status: {e5.status}")
    print(f"    code:   {e5.repair.get('code')}")

    # The repair.recorded status vocabulary:
    print(f"\n  repair.recorded status vocabulary:")
    for status in ["incident_captured", "repair_started", "agent_completed",
                    "diff_scope_checked", "rerun_started", "accepted", "rejected"]:
        print(f"    {status}")


# ---------------------------------------------------------------------------
# Part 6: Multiple exception types
# ---------------------------------------------------------------------------

def part6_multiple_exceptions() -> None:
    print("\n" + "=" * 60)
    print("PART 6: Multiple exception types — different repair policies")
    print("=" * 60)

    schema_agent = MockAgent(responses=["fix schema"])
    data_agent = MockAgent(responses=["fix data"])

    # A single stage can declare multiple exception -> policy mappings.
    def multi_error_stage() -> list[dict]:
        return []

    config = build_stage_config(
        multi_error_stage,
        name="multi_error_stage",
        readable=[DATA_FILE],
        editable=[DATA_FILE],
        on_error={
            ImportSchemaError: {
                "response": "agent_repair",
                "agent": schema_agent,
                "goal": "Fix CSV column schema.",
                "validators": [JsonRequired(keys=["paid_count"])],
            },
            DataValidationError: {
                "response": "agent_repair",
                "agent": data_agent,
                "goal": "Fix invalid data values in CSV.",
                "validators": [JsonRequired(keys=["paid_count"])],
            },
        },
    )

    print(f"\n  repair_policies: {len(config.repair_policies)}")
    for policy in config.repair_policies:
        print(f"\n  {policy.exception_type.__name__}:")
        print(f"    agent: {policy.to_dict()['agent']}")
        print(f"    goal:  {policy.goal}")

    # Exception matching: the first policy whose exception_type matches wins.
    print(f"\n  on_error dispatch:")
    print(f"    ImportSchemaError  -> schema repair agent")
    print(f"    DataValidationError -> data repair agent")
    print(f"    ValueError         -> no match (propagates as stage.exception)")

    # Subclass matching works: a subclass of ImportSchemaError matches.
    class CsvDelimiterError(ImportSchemaError):
        pass

    # In the actual stage decorator, isinstance() is used for matching.
    exc = CsvDelimiterError("bad delimiter")
    matched = isinstance(exc, ImportSchemaError)
    print(f"\n  CsvDelimiterError (subclass of ImportSchemaError):")
    print(f"    isinstance match: {matched}")
    print(f"    -> Would route to schema repair agent")


# ---------------------------------------------------------------------------
# Part 7: What scoped repair won't do
# ---------------------------------------------------------------------------

def part7_boundaries() -> None:
    print("\n" + "=" * 60)
    print("PART 7: What scoped repair won't do (by design)")
    print("=" * 60)

    print("""
    Scoped repair:
    - Will NOT repair agent-backed stages. on_error is only available on
      local (execution='local') stages. Agent stages use max_attempts and
      retry with diagnostics — not exception-based repair.
    - Will NOT retry repair. One repair attempt per exception. If the repair
      agent's output fails validation or the rerun raises again, the stage
      fails with complete diagnostics. No recursive repair.
    - Will NOT accept out-of-scope edits. The diff-scope verdict rejects
      changes to files not declared in editable. This is the core safety
      guarantee: the repair agent's reach is bounded.
    - Will NOT merge repair patches. The staged workspace is a full copy.
      If the repair agent edits a file, the entire file is the new version.
      There is no merge or rebase step.
    - Will NOT fall back to a different agent. One exception type maps to
      one policy with one agent. If that agent can't repair, the stage fails.
    - Will NOT catch undeclared exceptions. Only exception types listed in
      on_error trigger repair. Unlisted exceptions propagate as normal
      stage.exception diagnostics.

    DiffScopeVerdict:
    - Will NOT do semantic review. It checks paths, not content. An agent
      that makes a correct edit to an undeclared file is still rejected.
    - Will NOT handle symlinks or special files as text. They get
      fingerprinted by content/target, but no unified diff is produced.
    - Will NOT compare across different workspace backends. Both roots
      must be local filesystem directories.

    MockAgent and repair:
    - Will NOT edit files during repair. MockAgent returns scripted text
      and cannot modify the staged workspace. Tests using MockAgent will
      always produce repair.unsupported or repair.no_changes diagnostics.
    - Will NOT simulate partial repairs. For testing repair acceptance,
      you need either a real file-capable agent or manual workspace
      modification between the before-snapshot and diff evaluation.
    """)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    part1_repair_policy()
    part2_lifecycle()
    part3_diff_scope()
    part4_mock_agent_limits()
    part5_repair_events()
    part6_multiple_exceptions()
    part7_boundaries()

    # Cleanup.
    shutil.rmtree(EXAMPLE_DIR, ignore_errors=True)
