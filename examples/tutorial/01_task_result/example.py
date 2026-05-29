"""Tutorial 01: TaskResult and Task — the execution boundary.

Part 1: TaskResult as a standalone envelope — construction, field semantics,
        helpers, serialization, immutability.
Part 2: Task as the explicit run API — single-prompt tasks, multi-phase tasks,
        persistence requirements, and what Task deliberately won't do.
Part 3: Diagnostic severity levels, structured details, and how downstream
        code should consume them.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from accentor.core.task import Diagnostic, TaskResult, TaskResultError
from accentor.core.task.definitions import Task
from accentor.core.steps.phases import Phase
from accentor.dispatch.agents.providers.mock import MockAgent


# ---------------------------------------------------------------------------
# Part 1: TaskResult as a standalone envelope
# ---------------------------------------------------------------------------

def part1_task_result_basics() -> None:
    print("=" * 60)
    print("PART 1: TaskResult — the standard return envelope")
    print("=" * 60)

    # A TaskResult is a frozen dataclass. You construct it yourself when
    # building custom boundaries, or you receive it from @workflow / Task.run().

    success = TaskResult(
        ok=True,
        output={"title": "CSV import fixed", "priority": "high"},
        diagnostics=[
            Diagnostic.info(
                "validation.passed",
                "All validators accepted.",
                source="tutorial",
            )
        ],
        attempt_count=1,
    )

    # On success, best_output is automatically set to output if not provided.
    print(f"\n--- Successful result ---")
    print(f"ok:            {success.ok}")
    print(f"output:        {success.output}")
    print(f"best_output:   {success.best_output}")
    print(f"attempt_count: {success.attempt_count}")
    print(f"diagnostics:   {len(success.diagnostics)} (info-level)")

    # Failed result with partial output preserved as best_output.
    failure = TaskResult(
        ok=False,
        output=None,
        best_output={"title": "CSV import fixed"},
        diagnostics=[
            Diagnostic.error(
                "validation.missing_key",
                "Missing required key: priority.",
                source="JsonRequired",
                details={"key": "priority"},
            ),
            Diagnostic.warning(
                "validation.title_length",
                "Title has 4 words; max is 3.",
                source="TitleMaxWords",
                hint="Shorten the title or raise max_words.",
            ),
        ],
        attempt_count=2,
    )

    print(f"\n--- Failed result ---")
    print(f"ok:            {failure.ok}")
    print(f"output:        {failure.output}")
    print(f"best_output:   {failure.best_output}")
    print(f"attempt_count: {failure.attempt_count}")

    # --- Helpers: unwrap, output_or, best_available, require_ok ---

    print(f"\n--- Helpers ---")

    # unwrap() returns output on success, raises TaskResultError on failure.
    data = success.unwrap()
    print(f"success.unwrap():       {data}")

    try:
        failure.unwrap()
    except TaskResultError as exc:
        print(f"failure.unwrap() raised: {exc}")

    # output_or() returns output on success, the default on failure.
    print(f"success.output_or({{}}):  {success.output_or({})}")
    print(f"failure.output_or({{}}):  {failure.output_or({})}")

    # best_available() returns output > best_output > output (for failures).
    print(f"failure.best_available(): {failure.best_available()}")

    # require_ok() returns self or raises — useful for chaining.
    try:
        failure.require_ok()
    except TaskResultError:
        print(f"failure.require_ok():   raised TaskResultError")

    # --- Immutability ---
    print(f"\n--- Immutability ---")
    try:
        success.ok = False  # type: ignore[misc]
    except AttributeError as exc:
        print(f"Cannot mutate: {exc}")

    # --- Serialization ---
    print(f"\n--- JSON serialization ---")
    serialized = failure.to_json()
    roundtrip = json.loads(serialized)
    print(f"to_json() keys: {sorted(roundtrip.keys())}")
    print(f"roundtrip ok:   {roundtrip['ok']}")
    print(f"diagnostics[0]: {roundtrip['diagnostics'][0]['code']}")


# ---------------------------------------------------------------------------
# Part 2: Task — the explicit run API
# ---------------------------------------------------------------------------

def part2_task_api() -> None:
    print("\n" + "=" * 60)
    print("PART 2: Task — the explicit run API")
    print("=" * 60)

    # --- Single-prompt task ---
    from accentor.evaluate.validation import JsonRequired

    agent = MockAgent(responses=[json.dumps({"title": "Fix", "body": "Details"})])

    task = Task(
        name="quick_summary",
        agent=agent,
        prompt="Summarize the issue as JSON with 'title' and 'body' keys.",
        validators=[JsonRequired(keys=["title", "body"])],
    )

    result = task.run()
    print(f"\n--- Single-prompt task ---")
    print(f"ok:     {result.ok}")
    print(f"output: {result.output}")

    # --- Task with no agent: structured error, not a crash ---
    no_agent_task = Task(name="missing_agent", prompt="Do something.")
    result = no_agent_task.run()
    print(f"\n--- Task without agent ---")
    print(f"ok:          {result.ok}")
    print(f"diagnostic:  {result.diagnostics[0].code}")
    print(f"  message:   {result.diagnostics[0].message}")

    # --- Task with no work: neither prompt nor phases ---
    empty_task = Task(name="empty_task", agent=MockAgent(responses=["hi"]))
    result = empty_task.run()
    print(f"\n--- Task with no prompt and no phases ---")
    print(f"ok:          {result.ok}")
    print(f"diagnostic:  {result.diagnostics[0].code}")

    # --- Multi-phase task: requires persistence ---
    persistent_agent = MockAgent(
        responses=["I read the guidelines.", "The answer is 42."],
        session="persistent",
    )

    guideline_path = Path(tempfile.mktemp(suffix=".txt"))
    guideline_path.write_text("The answer to everything is 42.")

    task = Task(
        name="read_and_answer",
        agent=persistent_agent,
        phases=[
            Phase("read", "Read the guideline file.", workspace_files=[guideline_path]),
            Phase("answer", "What is the answer?", revoke_files=[guideline_path]),
        ],
    )

    result = task.run()
    print(f"\n--- Multi-phase task (persistent session) ---")
    print(f"ok:            {result.ok}")
    print(f"attempt_count: {result.attempt_count}")
    print(f"output:        {result.output}")

    guideline_path.unlink(missing_ok=True)

    # --- Non-persistent agent with multiple phases: structured refusal ---
    non_persistent = MockAgent(responses=["a", "b"])
    task = Task(
        name="two_phase_no_persistence",
        agent=non_persistent,
        phases=[
            Phase("phase_a", "First prompt."),
            Phase("phase_b", "Second prompt."),
        ],
    )
    result = task.run()
    print(f"\n--- Multi-phase + non-persistent agent ---")
    print(f"ok:          {result.ok}")
    print(f"diagnostic:  {result.diagnostics[0].code}")
    print(f"  message:   {result.diagnostics[0].message}")


# ---------------------------------------------------------------------------
# Part 3: Diagnostic depth
# ---------------------------------------------------------------------------

def part3_diagnostics() -> None:
    print("\n" + "=" * 60)
    print("PART 3: Diagnostics — structured error reporting")
    print("=" * 60)

    # Diagnostics have five severity levels.
    levels = [
        Diagnostic.debug("dbg.trace", "Extraction found JSON in text.", source="JsonExtractor"),
        Diagnostic.info("val.passed", "All validators accepted.", source="gate"),
        Diagnostic.warning("val.near_miss", "Title has 9 words; max is 10.", source="TitleMaxWords"),
        Diagnostic.error("val.failed", "Missing key: summary.", source="JsonRequired"),
        Diagnostic.critical("agent.timeout", "Agent did not respond in 30s.", source="CodexCli"),
    ]

    print(f"\n--- Severity levels ---")
    for d in levels:
        print(f"  [{d.severity:8s}] {d.code}: {d.message}")

    # Diagnostics carry structured details for machine consumption.
    d = Diagnostic.error(
        "validation.array_length",
        "Array 'risks' has 1 item; expected 2.",
        source="ArrayLength",
        details={"field": "risks", "actual": 1, "expected": 2},
    )
    print(f"\n--- Structured details ---")
    print(f"  code:    {d.code}")
    print(f"  details: {dict(d.details)}")
    print(f"  hint:    {d.hint}")

    # Diagnostics with hints help the consumer (or retry prompt) self-correct.
    d = Diagnostic.error(
        "validation.forbidden_pattern",
        "Output contains internal ticket ID: ENG-1234.",
        source="ForbiddenPattern",
        hint="Remove ticket IDs before responding.",
        details={"pattern": r"\b[A-Z]{2,10}-\d+\b", "label": "ticket IDs"},
    )
    print(f"\n--- Hint for remediation ---")
    print(f"  message: {d.message}")
    print(f"  hint:    {d.hint}")

    # Diagnostics are frozen — they cannot be mutated after creation.
    try:
        d.message = "changed"  # type: ignore[misc]
    except AttributeError:
        print(f"\n  Diagnostics are immutable (frozen dataclass).")

    # to_dict() produces a JSON-stable record for artifact storage.
    print(f"\n--- Serialization ---")
    record = d.to_dict()
    print(f"  to_dict() keys: {sorted(record.keys())}")


# ---------------------------------------------------------------------------
# What TaskResult / Task deliberately won't do
# ---------------------------------------------------------------------------

def part4_boundaries() -> None:
    print("\n" + "=" * 60)
    print("PART 4: What Accentor won't do (by design)")
    print("=" * 60)

    print("""
    TaskResult:
    - Will NOT auto-retry. It is a frozen record of what happened.
      Retry logic lives in @stage(max_attempts=N) or retry().
    - Will NOT parse or transform output. It stores what the gate accepted.
    - Will NOT merge results. Each boundary produces one TaskResult.

    Task:
    - Will NOT manage multi-agent orchestration. One Task = one agent.
    - Will NOT grant write/network access in phases. Phase v1 is read-only.
    - Will NOT run phases without adapter persistence. It checks capabilities
      upfront and returns a structured diagnostic if persistence is missing.
    - Will NOT evaluate semantic correctness. Validators are deterministic
      checks (JSON shape, text patterns, file existence), not model judgment.

    Diagnostic:
    - Will NOT contain raw sensitive data from redacted stages. Observation
      policy controls what reaches diagnostics, events, and artifacts.
    - Will NOT suggest fixes. The hint field is for human/prompt guidance,
      not executable repair logic.
    """)


if __name__ == "__main__":
    part1_task_result_basics()
    part2_task_api()
    part3_diagnostics()
    part4_boundaries()
