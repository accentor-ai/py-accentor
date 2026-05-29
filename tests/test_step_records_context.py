from __future__ import annotations

import json
from pathlib import Path

import pytest

from accentor.core.steps import Step, StepContext, StepKind, StepResult
from accentor.core.task import Diagnostic, TaskEvent
from accentor.record.observe import TaskObserver


def assert_json_stable(payload: object) -> object:
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    decoded = json.loads(encoded)
    assert json.dumps(decoded, allow_nan=False, sort_keys=True) == encoded
    return decoded


def test_step_kind_values_are_stable_event_log_strings() -> None:
    assert [kind.value for kind in StepKind] == [
        "execute",
        "dispatch",
        "extract",
        "validate",
        "route",
        "recover",
        "commit",
    ]
    assert str(StepKind.EXECUTE) == "execute"
    assert StepKind("validate") is StepKind.VALIDATE
    assert json.loads(json.dumps({"kind": StepKind.ROUTE})) == {"kind": "route"}


def test_step_context_root_and_child_derivation_preserve_runtime_handles(tmp_path: Path) -> None:
    observer = TaskObserver()
    root = StepContext.root(
        run_id="run-001",
        task_id="support-triage",
        artifact_root=tmp_path / "artifacts",
        observer=observer,
        metadata={"workflow": "support_triage"},
    )

    child = root.derive(
        stage="summarize_issue",
        attempt=1,
        routing={"selected": "billing"},
        validation={"ok": False, "validator": "json_required"},
        metadata={"stage_kind": "agent"},
    )

    assert child is not root
    assert child.stage == "summarize_issue"
    assert child.attempt == 1
    assert child.artifact_root == root.artifact_root
    assert child.artifact_store is root.artifact_store
    assert child.observer is observer
    assert child.routing_decisions["selected"] == "billing"
    assert child.validation_state["ok"] is False
    assert child.metadata["workflow"] == "support_triage"
    assert child.metadata["stage_kind"] == "agent"

    payload = assert_json_stable(child.to_dict())
    assert payload["stage"] == "summarize_issue"
    assert payload["observer"] == {"type": "TaskObserver", "event_count": 0}
    assert payload["artifact_store"]["root"] == str(root.artifact_store.root)


def test_step_context_with_updates_replaces_json_state(tmp_path: Path) -> None:
    ctx = StepContext(
        run_id="run-001",
        task_id="support-triage",
        artifact_root=tmp_path / "artifacts",
        routing={"selected": "billing"},
        validation={"ok": False},
        metadata={"attempt": 0},
    )

    updated = ctx.with_updates(
        routing_decisions={"selected": "technical"},
        validation_state={"ok": True},
        metadata={"attempt": 1},
    )

    assert updated.routing == {"selected": "technical"}
    assert updated.validation == {"ok": True}
    assert updated.metadata == {"attempt": 1}
    with pytest.raises(TypeError, match="unknown StepContext field"):
        ctx.with_updates(unknown=True)


def test_step_injects_context_only_when_callable_declares_ctx(tmp_path: Path) -> None:
    ctx = StepContext(
        run_id="run-001",
        task_id="support-triage",
        stage="summarize_issue",
        artifact_root=tmp_path / "artifacts",
    )

    def plain_step() -> str:
        return "plain result"

    def contextual_step(*, ctx: StepContext) -> dict[str, object]:
        return {"stage": ctx.stage, "attempt": ctx.attempt}

    plain_result = Step("plain", plain_step, kind=StepKind.EXECUTE)(ctx)
    contextual_result = Step("contextual", contextual_step, kind="dispatch")(ctx)

    assert plain_result.ok is True
    assert plain_result.output == "plain result"
    assert plain_result.step == "plain"
    assert plain_result.kind is StepKind.EXECUTE
    assert contextual_result.output == {"stage": "summarize_issue", "attempt": 0}
    assert contextual_result.kind is StepKind.DISPATCH


def test_step_normalizes_structured_results_and_exceptions(tmp_path: Path) -> None:
    ctx = StepContext(run_id="run-001", task_id="support-triage", attempt=2, artifact_root=tmp_path / "artifacts")

    def returns_step_result() -> StepResult:
        return StepResult.success({"accepted": True})

    def fails() -> str:
        raise ValueError("bad candidate")

    accepted = Step("validate_output", returns_step_result, kind=StepKind.VALIDATE).run(ctx)
    failed = Step("recover_output", fails, kind=StepKind.RECOVER).run(ctx)

    assert accepted.step == "validate_output"
    assert accepted.kind is StepKind.VALIDATE
    assert accepted.context is ctx
    assert accepted.attempt == 2
    assert failed.ok is False
    assert failed.diagnostics[0].code == "step.exception"
    assert failed.diagnostics[0].details["exception_type"] == "ValueError"


def test_step_result_serializes_metadata_events_and_artifacts(tmp_path: Path) -> None:
    ctx = StepContext(
        run_id="run-001",
        task_id="support-triage",
        stage="validate_output",
        attempt=1,
        artifact_root=tmp_path / "artifacts",
    )
    artifact = ctx.artifact_store.write_json("validation_report.json", {"ok": False})
    diagnostic = Diagnostic.warning("validation.retry", "Retry after invalid output.", source="validator")
    event = TaskEvent.validation_recorded(
        validation={"ok": False},
        stage="validate_output",
        attempt=1,
        diagnostics=[diagnostic],
    )

    result = StepResult.failure(
        diagnostic=diagnostic,
        best_output={"draft": "missing required field"},
        step="validate_output",
        kind="validate",
        context=ctx,
        events=[event],
        artifacts=[artifact],
        metadata={"validator": "JsonRequired"},
    )

    payload = assert_json_stable(result.to_dict())
    assert payload["ok"] is False
    assert payload["step"] == "validate_output"
    assert payload["kind"] == "validate"
    assert payload["attempt"] == 1
    assert payload["best_output"] == {"draft": "missing required field"}
    assert payload["artifacts"][0]["name"] == "validation_report.json"
    assert payload["context"]["stage"] == "validate_output"
    assert result.to_task_result().attempt_count == 2


def test_step_records_reject_non_json_metadata(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="JSON-compatible"):
        StepContext(
            run_id="run-001",
            task_id="support-triage",
            artifact_root=tmp_path / "artifacts",
            metadata={"bad": object()},
        )
    with pytest.raises(TypeError, match="JSON-compatible"):
        StepResult(ok=True, metadata={"bad": object()})
    with pytest.raises(TypeError, match="JSON-compatible"):
        Step("bad", metadata={"bad": object()})
