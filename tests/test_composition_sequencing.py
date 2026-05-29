from __future__ import annotations

import json

import pytest

from accentor.core.composition import retry, sequence
from accentor.core.steps import Step, StepContext, StepResult
from accentor.core.task import TaskResult
from accentor.core.task.diagnostics import Diagnostic


def assert_json_stable(payload: dict) -> dict:
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    return json.loads(encoded)


def test_sequence_runs_plain_callables_in_order_and_passes_outputs() -> None:
    calls: list[str] = []

    def first(value: int) -> int:
        calls.append("first")
        return value + 1

    def second(value: int) -> int:
        calls.append("second")
        return value * 3

    result = sequence([first, second], initial_input=2, name="math")

    assert result.ok is True
    assert result.output == 9
    assert calls == ["first", "second"]
    assert result.attempt_count == 2


def test_sequence_accepts_step_objects_and_injects_context_only_when_declared() -> None:
    seen_attempts: list[int] = []

    def with_ctx(value: str, *, ctx: StepContext) -> StepResult:
        seen_attempts.append(ctx.attempt)
        return StepResult.success(value.upper(), context=ctx)

    def without_ctx(value: str) -> str:
        return f"{value}!"

    ctx = StepContext.root(run_id="run-1", task_id="task-1")
    result = sequence([Step("upper", with_ctx), without_ctx], initial_input="ok", ctx=ctx)

    assert result.ok is True
    assert result.output == "OK!"
    assert seen_attempts == [0]


def test_sequence_short_circuits_after_failed_step() -> None:
    calls: list[str] = []

    def fail(value: str) -> StepResult:
        calls.append("fail")
        return StepResult.failure(
            diagnostic=Diagnostic.error("demo.failed", "failed"),
            best_output=value,
        )

    def after(value: str) -> str:
        calls.append("after")
        return value

    result = sequence([fail, after], initial_input="candidate")

    assert result.ok is False
    assert result.best_output == "candidate"
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["demo.failed"]
    assert calls == ["fail"]


def test_sequence_converts_callable_exception_to_structured_failure() -> None:
    def boom(_: object) -> object:
        raise ValueError("nope")

    result = sequence([boom], initial_input="x")

    assert result.ok is False
    assert result.diagnostics[0].code == "step.exception"
    assert result.diagnostics[0].details["exception_type"] == "ValueError"
    assert_json_stable(result.to_dict())


def test_retry_succeeds_after_failure_and_preserves_earlier_diagnostics() -> None:
    calls = 0
    failures: list[int] = []

    def flaky() -> StepResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return StepResult.failure(
                diagnostic=Diagnostic.error("demo.once", "first failed"),
                best_output="bad",
            )
        return StepResult.success("good")

    result = retry(flaky, max_attempts=2, on_attempt_failure=lambda _result, attempt: failures.append(attempt))

    assert result.ok is True
    assert result.output == "good"
    assert result.attempt_count == 2
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["demo.once"]
    assert failures == [0]
    assert [event.event_type for event in result.events].count("attempt.started") == 2


def test_retry_derives_attempt_contexts_and_preserves_root_metadata() -> None:
    attempts: list[tuple[int, str]] = []
    ctx = StepContext.root(run_id="run-1", task_id="task-1", metadata={"source": "test"})

    def always_fail(*, ctx: StepContext) -> StepResult:
        attempts.append((ctx.attempt, ctx.metadata["source"]))
        return StepResult.failure(diagnostic=Diagnostic.error("demo.fail", "failed"))

    result = retry(always_fail, max_attempts=2, ctx=ctx, name="unstable")

    assert result.ok is False
    assert result.attempt_count == 2
    assert attempts == [(0, "test"), (1, "test")]
    assert result.diagnostics[-1].code == "retry.exhausted"
    assert_json_stable(result.to_dict())


def test_retry_stops_on_non_retryable_failure() -> None:
    def fail() -> StepResult:
        return StepResult.failure(diagnostic=Diagnostic.error("demo.no_retry", "failed"))

    result = retry(fail, max_attempts=3, retry_on=lambda _result, attempt: attempt > 10)

    assert result.ok is False
    assert result.attempt_count == 1
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["demo.no_retry"]


def test_retry_validates_max_attempts() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        retry(lambda: "unused", max_attempts=0)


def test_retry_preserves_task_result_shape_from_operation() -> None:
    task_result = TaskResult(
        ok=False,
        best_output="candidate",
        diagnostics=[Diagnostic.error("task.failed", "failed")],
        attempt_count=4,
    )

    result = retry(lambda: task_result, max_attempts=1)

    assert result.ok is False
    assert result.best_output == "candidate"
    assert result.attempt_count == 1
    assert result.diagnostics[0].code == "task.failed"
