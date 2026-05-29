from __future__ import annotations

import json

import pytest

from accentor.core.task.diagnostics import Diagnostic
from accentor.core.task.events import TaskEvent
from accentor.record.observe import JsonlSink, ObservationPolicy, TaskObserver


def make_event(**details: object) -> TaskEvent:
    return TaskEvent.stage_completed(
        workflow="support_flow",
        task="run-001",
        stage="draft_response",
        details=details,
    )


class CapturingSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.flush_count = 0
        self.close_count = 0

    def emit(self, event: dict[str, object]) -> None:
        self.events.append(event)

    def flush(self) -> None:
        self.flush_count += 1

    def close(self) -> None:
        self.close_count += 1


def test_task_observer_captures_and_forwards_events() -> None:
    sink = CapturingSink()
    observer = TaskObserver([sink])

    event = observer.emit(make_event(status="ok", output={"reply": "done"}))

    assert observer.events == [event]
    assert sink.events == [event]
    assert event["event_type"] == "stage.completed"
    assert event["diagnostics"] == []
    assert event["details"] == {"status": "ok", "output": {"reply": "done"}}


def test_jsonl_sink_writes_valid_single_line_json(tmp_path) -> None:
    sink = JsonlSink(tmp_path)
    observer = TaskObserver([sink])

    observer.emit(make_event(status="ok", count=1))
    observer.close()

    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event_type"] == "stage.completed"
    assert event["task"] == "run-001"
    assert event["stage"] == "draft_response"
    assert event["details"] == {"count": 1, "status": "ok"}
    assert "\n" not in lines[0]


def test_task_observer_flush_and_close_are_forwarded_once() -> None:
    sink = CapturingSink()
    observer = TaskObserver([sink])

    observer.flush()
    observer.close()
    observer.close()

    assert sink.flush_count == 2
    assert sink.close_count == 1
    with pytest.raises(ValueError, match="closed"):
        observer.emit(make_event(status="late"))


def test_sensitive_prompt_and_input_fields_are_redacted_from_jsonl(tmp_path) -> None:
    sink = JsonlSink(tmp_path)
    observer = TaskObserver([sink])

    observer.emit(
        make_event(
            prompt="Contact dana.park@example.com about the duplicate charge.",
            input={"raw_note": "dana.park@example.com"},
            visible_summary="redaction happened",
        )
    )
    observer.close()

    output = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "dana.park@example.com" not in output

    event = json.loads(output)
    assert event["details"]["prompt"] == "[REDACTED]"
    assert event["details"]["input"] == "[REDACTED]"
    assert event["details"]["visible_summary"] == "redaction happened"


def test_task_observer_serializes_canonical_diagnostics() -> None:
    observer = TaskObserver()
    event = TaskEvent.stage_completed(
        stage="validate_output",
        diagnostics=[
            Diagnostic.warning(
                "validation.retry",
                "Retrying after validation failure.",
                source="validator",
                details={"attempt": 0},
            )
        ],
    )

    serialized = observer.emit(event)

    assert serialized["diagnostics"] == [
        {
            "code": "validation.retry",
            "message": "Retrying after validation failure.",
            "severity": "warning",
            "source": "validator",
            "hint": None,
            "details": {"attempt": 0},
        }
    ]


def test_redaction_policy_can_be_disabled_for_restricted_logs() -> None:
    observer = TaskObserver(
        policy=ObservationPolicy(redact_sensitive_fields=False),
    )

    event = observer.emit(make_event(prompt="internal prompt"))

    assert event["details"]["prompt"] == "internal prompt"
