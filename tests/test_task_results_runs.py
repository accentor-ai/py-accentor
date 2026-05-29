from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from accentor.core.task import TaskAttempt, TaskEvent, TaskResult, TaskResultError, TaskRun
from accentor.core.task.diagnostics import Diagnostic
from accentor.record.artifacts import ArtifactStore


def assert_json_stable(payload: Any) -> Any:
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    decoded = json.loads(encoded)
    assert json.dumps(decoded, allow_nan=False, sort_keys=True) == encoded
    return decoded


def test_task_result_success_helpers_and_pinned_fields() -> None:
    output = {"answer": 42}
    result = TaskResult(
        ok=True,
        output=output,
        diagnostics=[Diagnostic.info("validation.accepted", "Output passed validation.")],
        attempt_count=1,
    )

    assert result.unwrap() is output
    assert result.require_ok() is result
    assert result.output_or({"fallback": True}) is output
    assert result.best_available() is output
    assert result.best_output is output
    assert list(result.to_dict()) == [
        "ok",
        "output",
        "best_output",
        "diagnostics",
        "attempt_count",
        "events",
        "artifacts",
    ]


def test_task_result_failure_preserves_best_output_and_raises_with_result() -> None:
    diagnostic = Diagnostic.error("validation.failed", "Output was not valid JSON.", source="validator")
    result = TaskResult(ok=False, best_output="not json", diagnostics=[diagnostic], attempt_count=2)

    assert result.output is None
    assert result.output_or("fallback") == "fallback"
    assert result.best_available() == "not json"

    with pytest.raises(TaskResultError, match=r"\[validation.failed\]") as unwrap_error:
        result.unwrap()
    with pytest.raises(TaskResultError) as require_error:
        result.require_ok()

    assert unwrap_error.value.result is result
    assert require_error.value.result is result


def test_task_result_serializes_diagnostics_events_and_artifact_records(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    artifact = store.write_json("validation_report.json", {"ok": True})
    event = TaskEvent.stage_completed(
        workflow="support_triage",
        task="draft_response",
        stage="validate_output",
        attempt=0,
        validation={"ok": True},
        artifacts=[artifact.to_dict()],
    )
    result = TaskResult(
        ok=True,
        output={"reply": "done"},
        diagnostics=[Diagnostic.info("validation.accepted", "Accepted.")],
        attempt_count=1,
        events=[event],
        artifacts=[artifact],
    )

    payload = assert_json_stable(result.to_dict())
    assert payload["ok"] is True
    assert payload["output"] == {"reply": "done"}
    assert payload["best_output"] == {"reply": "done"}
    assert payload["events"][0]["validation"] == {"ok": True}
    assert payload["artifacts"][0]["name"] == "validation_report.json"

    store.write_json("task_result.json", result.to_dict())
    assert store.read_json("task_result.json") == payload
    assert json.loads(result.to_json()) == payload


def test_task_result_accepts_mapping_records_and_validates_attempt_count() -> None:
    diagnostic_payload = {
        "code": "validation.retry",
        "message": "Retrying after validation failure.",
        "severity": "warning",
    }
    event_payload = TaskEvent.attempt_completed(
        attempt=0,
        status="failed",
        diagnostics=[diagnostic_payload],
    ).to_dict()
    artifact_payload = {
        "name": "agent_response_attempt_0.txt",
        "path": "agent_response_attempt_0.txt",
        "size_bytes": 8,
        "sha256": "0" * 64,
    }

    result = TaskResult(
        ok=False,
        best_output="invalid",
        diagnostics=[diagnostic_payload],
        attempt_count=1,
        events=[event_payload],
        artifacts=[artifact_payload],
    )

    assert result.diagnostics[0].code == "validation.retry"
    assert result.events[0].event_type == "attempt.completed"
    assert result.to_dict()["artifacts"] == [artifact_payload]
    with pytest.raises(ValueError, match="attempt_count"):
        TaskResult(ok=False, attempt_count=-1)


def test_task_attempt_and_task_run_are_json_stable_records(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    artifact = store.write_text("events.jsonl", '{"event_type":"started"}\n')
    diagnostic = Diagnostic.warning("validation.retry", "Retry required.", source="validator")
    event = TaskEvent.attempt_completed(attempt=0, status="failed", diagnostics=[diagnostic])
    attempt = TaskAttempt(
        run_id="run-001",
        task_id="support-triage",
        attempt_index=0,
        status="failed",
        started_at="2026-05-28T00:00:00+00:00",
        completed_at=datetime(2026, 5, 28, 0, 0, 2, tzinfo=UTC),
        diagnostics=[diagnostic],
        events=[event],
        artifacts=[artifact],
    )
    run = TaskRun(
        run_id="run-001",
        task_id="support-triage",
        status="failed",
        started_at="2026-05-28T00:00:00+00:00",
        completed_at="2026-05-28T00:00:03+00:00",
        attempts=[attempt.to_dict()],
        diagnostics=[diagnostic],
        events=[event],
        artifacts=[artifact.to_dict()],
    )

    assert run.attempt_count == 1
    assert run.attempts[0].attempt_index == 0
    payload = assert_json_stable(run.to_dict())
    assert payload["run_id"] == "run-001"
    assert payload["task_id"] == "support-triage"
    assert payload["status"] == "failed"
    assert payload["attempts"][0]["completed_at"] == "2026-05-28T00:00:02+00:00"
    assert payload["attempts"][0]["artifacts"][0]["name"] == "events.jsonl"
    assert json.loads(run.to_json()) == payload


def test_task_run_validates_required_attempt_fields() -> None:
    with pytest.raises(ValueError, match="run_id"):
        TaskRun(run_id="", task_id="task", status="started")
    with pytest.raises(ValueError, match="attempt_index"):
        TaskAttempt(run_id="run", task_id="task", attempt_index=-1, status="failed")
