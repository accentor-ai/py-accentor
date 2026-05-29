"""Tutorial 02: Stage and Workflow — composing ordinary functions.

Part 1: Local stages as decorated Python functions, data flow between stages.
Part 2: Workflow as a TaskResult boundary — what it wraps, what it catches.
Part 3: Stage failure propagation — how one failing stage stops the workflow.
Part 4: return_result=False mode — exceptions instead of TaskResult.
Part 5: Calling stages outside a workflow — direct stage calls.
Part 6: What stages and workflows deliberately won't do.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from accentor.core.decorators import stage, workflow, WorkflowError


# ---------------------------------------------------------------------------
# Part 1: Local stages as decorated functions
# ---------------------------------------------------------------------------

SAMPLE_CSV = """\
order_id,amount,status
A001,49.99,paid
A002,19.50,pending
A003,120.00,paid
A004,35.00,cancelled
"""


@stage(name="parse_rows")
def parse_rows(raw_csv: str) -> list[dict[str, str]]:
    lines = raw_csv.strip().splitlines()
    headers = [h.strip() for h in lines[0].split(",")]
    rows = []
    for line in lines[1:]:
        values = [v.strip() for v in line.split(",")]
        rows.append(dict(zip(headers, values)))
    return rows


@stage(name="filter_paid")
def filter_paid(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("status") == "paid"]


@stage(name="summarize")
def summarize(paid_rows: list[dict[str, str]]) -> dict:
    return {
        "paid_count": len(paid_rows),
        "order_ids": [row["order_id"] for row in paid_rows],
        "total": sum(float(row["amount"]) for row in paid_rows),
    }


def part1_local_stages() -> None:
    print("=" * 60)
    print("PART 1: Local stages — decorated ordinary functions")
    print("=" * 60)

    # Inside a workflow, local stages return raw Python values.
    # The @stage decorator adds tracking, but the function behavior is normal.

    @workflow(name="order_summary")
    def order_summary(raw_csv: str) -> dict:
        rows = parse_rows(raw_csv)
        paid = filter_paid(rows)
        return summarize(paid)

    result = order_summary(SAMPLE_CSV)
    print(f"\nok:     {result.ok}")
    print(f"output: {json.dumps(result.output, indent=2)}")
    print(f"events: {len(result.events)} (workflow + stage start/complete)")


# ---------------------------------------------------------------------------
# Part 2: Workflow as a TaskResult boundary
# ---------------------------------------------------------------------------

def part2_workflow_boundary() -> None:
    print("\n" + "=" * 60)
    print("PART 2: Workflow as a TaskResult boundary")
    print("=" * 60)

    # A workflow catches exceptions and converts them to failed TaskResults.
    @workflow(name="crashing_workflow")
    def crashing_workflow() -> dict:
        raise RuntimeError("Unexpected data format")

    result = crashing_workflow()
    print(f"\nok:          {result.ok}")
    print(f"diagnostic:  {result.diagnostics[0].code}")
    print(f"  message:   {result.diagnostics[0].message}")

    # The workflow boundary catches ANY exception — the caller always gets
    # a TaskResult, never an unhandled crash.
    @workflow(name="type_error_workflow")
    def type_error_workflow() -> dict:
        return {"count": int("not_a_number")}  # type: ignore[arg-type]

    result = type_error_workflow()
    print(f"\nValueError from int():")
    print(f"ok:          {result.ok}")
    print(f"diagnostic:  {result.diagnostics[0].code}")

    # Non-dict return values are wrapped as output — workflows don't require JSON.
    @workflow(name="string_output")
    def string_output() -> str:
        return "just a string"

    result = string_output()
    print(f"\nString output from workflow:")
    print(f"ok:     {result.ok}")
    print(f"output: {result.output!r}")
    print(f"type:   {type(result.output).__name__}")


# ---------------------------------------------------------------------------
# Part 3: Stage failure propagation
# ---------------------------------------------------------------------------

def part3_stage_failure() -> None:
    print("\n" + "=" * 60)
    print("PART 3: Stage failure stops the workflow")
    print("=" * 60)

    @stage(name="validate_format")
    def validate_format(data: str) -> str:
        if not data.startswith("{"):
            raise ValueError(f"Expected JSON object, got: {data[:20]!r}")
        return data

    @stage(name="parse_json")
    def parse_json(data: str) -> dict:
        return json.loads(data)

    @workflow(name="json_pipeline")
    def json_pipeline(data: str) -> dict:
        validated = validate_format(data)
        return parse_json(validated)

    # Happy path: valid JSON
    result = json_pipeline('{"key": "value"}')
    print(f"\nValid JSON:")
    print(f"ok:     {result.ok}")
    print(f"output: {result.output}")

    # Failure path: invalid input — validate_format raises, parse_json never runs.
    result = json_pipeline("not json at all")
    print(f"\nInvalid input:")
    print(f"ok:          {result.ok}")
    print(f"diagnostic:  {result.diagnostics[0].code}")
    print(f"  message:   {result.diagnostics[0].message}")


# ---------------------------------------------------------------------------
# Part 4: return_result=False — exception-based workflows
# ---------------------------------------------------------------------------

def part4_exception_mode() -> None:
    print("\n" + "=" * 60)
    print("PART 4: return_result=False — raises on failure")
    print("=" * 60)

    @workflow(name="strict_pipeline", return_result=False)
    def strict_pipeline() -> dict:
        rows = parse_rows(SAMPLE_CSV)
        paid = filter_paid(rows)
        return summarize(paid)

    # On success, returns raw output (not wrapped in TaskResult).
    output = strict_pipeline()
    print(f"\nSuccess returns raw output:")
    print(f"type:   {type(output).__name__}")
    print(f"output: {json.dumps(output, indent=2)}")

    # On failure, raises WorkflowError carrying the TaskResult.
    @workflow(name="strict_failing", return_result=False)
    def strict_failing() -> dict:
        raise RuntimeError("bad data")

    try:
        strict_failing()
    except WorkflowError as exc:
        print(f"\nFailure raises WorkflowError:")
        print(f"  message: {exc}")
        print(f"  result:  ok={exc.result.ok}")


# ---------------------------------------------------------------------------
# Part 5: Calling stages outside a workflow
# ---------------------------------------------------------------------------

def part5_direct_stage_call() -> None:
    print("\n" + "=" * 60)
    print("PART 5: Direct stage calls (no workflow)")
    print("=" * 60)

    # A local stage without validators, called outside a workflow,
    # returns the raw Python value — no TaskResult wrapping.
    raw_output = parse_rows(SAMPLE_CSV)
    print(f"\nDirect call (no validators, no workflow):")
    print(f"type:  {type(raw_output).__name__}")
    print(f"count: {len(raw_output)} rows")

    # A stage WITH validators, called outside a workflow,
    # returns a TaskResult because validation creates a boundary.
    from accentor.evaluate.validation import JsonRequired

    @stage(
        name="validated_local_stage",
        validators=[JsonRequired(keys=["name", "age"])],
    )
    def validated_stage() -> str:
        return json.dumps({"name": "Alice", "age": 30})

    result = validated_stage()
    print(f"\nDirect call (with validators):")
    print(f"type:   {type(result).__name__}")
    print(f"ok:     {result.ok}")
    print(f"output: {result.output}")


# ---------------------------------------------------------------------------
# Part 6: What stages/workflows won't do
# ---------------------------------------------------------------------------

def part6_boundaries() -> None:
    print("\n" + "=" * 60)
    print("PART 6: What stages and workflows won't do (by design)")
    print("=" * 60)

    print("""
    Stages:
    - Will NOT auto-parallelize. Stages in a workflow run sequentially.
      Use separate workflows for parallelism.
    - Will NOT implicitly share state. Each stage receives explicit arguments
      and returns explicit output. No hidden context mutation.
    - Will NOT catch exceptions for you in local mode (without on_error).
      An unhandled exception in a local stage propagates to the workflow,
      which converts it to a failed TaskResult.
    - Will NOT validate local stage output unless you declare validators.
      Validation is opt-in, not automatic.

    Workflows:
    - Will NOT retry failed stages. Retry is per-stage (max_attempts) or
      explicit via the retry() composition helper.
    - Will NOT merge results from multiple stages. The workflow return value
      becomes the TaskResult output. Intermediate stage results are events.
    - Will NOT nest. You cannot call a @workflow from inside another @workflow.
      Compose by calling stages, or use sequence() for step chains.
    """)


if __name__ == "__main__":
    part1_local_stages()
    part2_workflow_boundary()
    part3_stage_failure()
    part4_exception_mode()
    part5_direct_stage_call()
    part6_boundaries()
