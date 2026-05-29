"""Focused example: agentic repair after a deterministic pipeline failure.

General purpose:
    Show how Accentor can treat agentic code repair as a scoped recovery path,
    not as the default way a pipeline runs. Ordinary Python owns the happy path;
    the agent is invited only after a declared exception type appears.

Toy setting:
    A CSV parser intentionally uses the wrong delimiter. That makes the expected
    columns disappear, raising a ValueError that triggers a repair policy with a
    narrow editable file set.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from accentor.core.decorators import stage, workflow
from accentor.dispatch.agents.providers.codex_cli import CodexCli
from accentor.evaluate.validation import RequiredFile, RequiredKeys


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "orders.csv"
OUTPUT_FILE = ROOT / "output" / "paid_orders_summary.json"

EXPECTED_COLUMNS = {"order_id", "amount", "status"}
# This is intentionally wrong for the example. The agent repair should discover
# that the CSV file is comma-delimited and patch this constant or equivalent
# parsing logic.
CSV_DELIMITER = "."  # intentionally wrong for the focused example


# The local stage fails deterministically when its assumptions do not match the
# fixture. The on_error block declares when and how an agent may attempt repair.
@stage(
    name="parse_orders",
    readable=[Path(__file__), DATA_FILE],
    editable=[Path(__file__)],
    on_error={
        ValueError: {
            "response": "agent_repair",
            "agent": CodexCli(sandbox="workspace-write"),
            "goal": "Repair CSV parsing so paid_orders_pipeline completes.",
            "validators": [
                # Repair is accepted only if the rerun produces the expected
                # artifact shape.
                RequiredFile(OUTPUT_FILE),
                RequiredKeys(
                    OUTPUT_FILE,
                    keys=["paid_order_count", "paid_order_ids", "paid_total_amount"],
                ),
            ],
        }
    },
)
def parse_orders(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=CSV_DELIMITER)
        missing = EXPECTED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            # The exception message is part of the repair incident. It should be
            # specific enough for an agent or human to diagnose the boundary.
            raise ValueError(
                f"CSV columns missing: {sorted(missing)}; "
                f"parsed={reader.fieldnames!r}; delimiter={CSV_DELIMITER!r}"
            )
        return list(reader)


@stage(name="summarize_paid_orders")
def summarize_paid_orders(rows: list[dict[str, str]]) -> dict:
    # After parsing succeeds, the rest of the workflow is conventional data
    # processing. No agent is needed for this happy path.
    paid = [row for row in rows if row["status"] == "paid"]
    return {
        "paid_order_count": len(paid),
        "paid_order_ids": [row["order_id"] for row in paid],
        "paid_total_amount": sum(float(row["amount"]) for row in paid),
    }


@stage(validators=[RequiredFile(OUTPUT_FILE)])
def write_summary(summary: dict) -> dict:
    # Writing an artifact gives the repair policy something concrete to validate
    # after it reruns the workflow.
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


@workflow(name="paid_orders_pipeline")
def paid_orders_pipeline() -> dict:
    # The workflow reads like normal Python. Accentor wraps the stages with
    # observation, recovery policy, and validation.
    rows = parse_orders(DATA_FILE)
    summary = summarize_paid_orders(rows)
    return write_summary(summary)


def _separator(label: str = "") -> None:
    if label:
        print(f"\n{'─' * 20} {label} {'─' * 20}")
    else:
        print(f"{'─' * 60}")


def _print_result(result) -> None:
    _separator("WORKFLOW: paid_orders_pipeline")

    print(f"Status   : {'PASS' if result.ok else 'FAIL'}")
    print(f"Attempts : {result.attempt_count}")

    stage_cfg = parse_orders.__accentor_stage_config__
    repair_policy = stage_cfg.on_error.get(ValueError)
    if repair_policy:
        _separator("REPAIR POLICY")
        print(f"  Trigger   : ValueError")
        print(f"  Response  : {repair_policy.response}")
        print(f"  Goal      : {repair_policy.goal}")
        if repair_policy.editable:
            print(f"  Editable  : {[str(p) for p in repair_policy.editable]}")
        if repair_policy.validators:
            print(f"  Validators: {', '.join(type(v).__name__ for v in repair_policy.validators)}")

    repair_events = [e for e in result.events if e.repair]
    if repair_events:
        _separator("REPAIR LIFECYCLE")
        for e in repair_events:
            r = e.repair
            print(f"  {r.get('status', '?'):12s}  {e.event_type}")
            if r.get("exception_type"):
                print(f"               exception: {r['exception_type']}")
            if r.get("goal"):
                print(f"               goal: {r['goal']}")

    if result.diagnostics:
        _separator("DIAGNOSTICS")
        for d in result.diagnostics:
            severity = d.severity.upper()
            source = f" (source: {d.source})" if d.source else ""
            print(f"  [{severity}] {d.code}{source}")
            print(f"           {d.message}")
            if d.hint:
                print(f"           hint: {d.hint}")

    if result.events:
        _separator("EVENTS ({} recorded)".format(len(result.events)))
        for e in result.events:
            ts = e.timestamp.split("T")[1][:12] if "T" in e.timestamp else e.timestamp
            label = e.stage or e.workflow or ""
            status = e.status or ""
            print(f"  {ts}  {e.event_type:25s} {label:30s} {status}")

    _separator("OUTPUT")
    if result.ok:
        print(json.dumps(result.output, indent=2))
    else:
        print("(best-effort output, did not pass validation)")
        print(result.best_output)

    _separator()


if __name__ == "__main__":
    result = paid_orders_pipeline()
    _print_result(result)
