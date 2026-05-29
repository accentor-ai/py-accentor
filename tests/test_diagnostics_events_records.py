from __future__ import annotations

import json

import pytest

from accentor.core.task.diagnostics import Diagnostic
from accentor.core.task.events import TaskEvent


def assert_json_stable(payload: dict) -> dict:
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    return json.loads(encoded)


def test_diagnostic_exposes_public_fields_and_default_severity() -> None:
    diagnostic = Diagnostic(
        code="validation.failed",
        message="Output did not match the requested schema.",
        source="validator",
        hint="Return a JSON object.",
        details={"path": ["items", 0], "secret_ref": "env:API_TOKEN", "redacted": True},
    )

    assert diagnostic.code == "validation.failed"
    assert diagnostic.message == "Output did not match the requested schema."
    assert diagnostic.severity == "error"
    assert diagnostic.source == "validator"
    assert diagnostic.hint == "Return a JSON object."
    assert diagnostic.details["secret_ref"] == "env:API_TOKEN"

    payload = assert_json_stable(diagnostic.to_dict())
    assert payload == {
        "code": "validation.failed",
        "message": "Output did not match the requested schema.",
        "severity": "error",
        "source": "validator",
        "hint": "Return a JSON object.",
        "details": {"path": ["items", 0], "secret_ref": "env:API_TOKEN", "redacted": True},
    }


def test_diagnostic_named_constructors_pin_string_severities() -> None:
    assert Diagnostic.debug("debug", "debug message").severity == "debug"
    assert Diagnostic.info("info", "info message").severity == "info"
    assert Diagnostic.warning("warning", "warning message").severity == "warning"
    assert Diagnostic.error("error", "error message").severity == "error"
    assert Diagnostic.critical("critical", "critical message").severity == "critical"


def test_diagnostic_details_are_json_ready_and_redaction_safe() -> None:
    diagnostic = Diagnostic.warning(
        code="sensitive.observation",
        message="Sensitive values were redacted before observation.",
        details={
            "redactions": [{"field": "token", "replacement": "[REDACTED]"}],
            "secret_ref": "env:PAYMENT_TOKEN",
            "raw_secret": None,
        },
    )

    payload = assert_json_stable(diagnostic.to_dict())
    assert payload["details"]["raw_secret"] is None
    assert payload["details"]["secret_ref"] == "env:PAYMENT_TOKEN"

    with pytest.raises(TypeError):
        Diagnostic(code="bad.details", message="Bad details", details={"not_json": object()})


def test_task_event_serializes_workflow_metadata_without_provider_fields() -> None:
    event = TaskEvent(
        event_type="stage.completed",
        timestamp="2026-05-28T00:00:00+00:00",
        workflow="triage",
        task="support-routing",
        stage="classify",
        attempt=1,
        status="validated",
        message="Stage completed with accepted output.",
        diagnostics=[
            {
                "code": "validation.retry",
                "message": "First attempt failed validation.",
                "severity": "warning",
            }
        ],
        artifacts=[{"path": "validation_report.json", "kind": "validation_report"}],
        validation={"ok": True, "validator": "json_fields"},
        routing={"selected": "billing", "omitted": ["technical"]},
        repair={"attempted": False, "reason": "not_needed"},
        details={"redacted": True, "secret_ref": "env:PAYMENT_TOKEN"},
    )

    payload = assert_json_stable(event.to_dict())
    assert payload["event_type"] == "stage.completed"
    assert payload["workflow"] == "triage"
    assert payload["task"] == "support-routing"
    assert payload["stage"] == "classify"
    assert payload["attempt"] == 1
    assert payload["diagnostics"][0]["severity"] == "warning"
    assert payload["artifacts"] == [{"path": "validation_report.json", "kind": "validation_report"}]
    assert payload["validation"]["ok"] is True
    assert payload["routing"]["selected"] == "billing"
    assert payload["repair"]["attempted"] is False
    assert "provider" not in payload


def test_task_event_common_constructors_set_defaults() -> None:
    started = TaskEvent.workflow_started(workflow="triage")
    stage = TaskEvent.stage_completed(stage="classify", attempt=0, validation={"ok": True})
    routed = TaskEvent.routing_decided(routing={"selected": "billing"})
    artifact = TaskEvent.artifact_recorded(artifact={"path": "events.jsonl", "kind": "event_log"})

    assert started.event_type == "workflow.started"
    assert started.status == "started"
    assert stage.event_type == "stage.completed"
    assert stage.status == "completed"
    assert stage.validation["ok"] is True
    assert routed.event_type == "routing.decided"
    assert routed.status == "selected"
    assert artifact.to_dict()["artifacts"] == [{"path": "events.jsonl", "kind": "event_log"}]


def test_observe_events_is_compatibility_reexport_only() -> None:
    from accentor.record.observe.events import TaskEvent as ObserveTaskEvent

    assert ObserveTaskEvent is TaskEvent
