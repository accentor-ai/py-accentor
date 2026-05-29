from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from accentor.core.composition import (
    GateAttempt,
    GateReport,
    build_validation_report,
    run_validation_pipeline,
    validate_candidate,
)
from accentor.core.task import TaskResult
from accentor.evaluate.validation import (
    ContainsPhrase,
    JsonRequired,
    NoMarkdownFences,
    ValidationContext,
    ValidationResult,
    Validator,
)


class RecordsContext(Validator):
    def __init__(self) -> None:
        self.context: ValidationContext | None = None

    def validate(self, candidate: Any = None, context: ValidationContext | None = None):
        self.context = context
        if context is None or not context.parsed_available:
            return ValidationResult.failure("Expected parsed JSON before validation.", validator=self)
        return ValidationResult.success(validator=self.__class__.__name__)


class RecordsRawCheck(Validator):
    def __init__(self) -> None:
        self.seen: Any = None

    def check(self, output: Any) -> list[str]:
        self.seen = output
        return []


def test_gate_extracts_embedded_json_before_validation() -> None:
    validator = RecordsContext()

    attempt = validate_candidate(
        'Agent said:\n{"title": "Accepted", "items": [1, 2]}',
        validators=[validator, JsonRequired(keys=["title", "items"])],
    )

    assert isinstance(attempt, GateAttempt)
    assert attempt.ok is True
    assert validator.context is not None
    assert validator.context.parsed_json == {"title": "Accepted", "items": [1, 2]}
    assert attempt.output == {"title": "Accepted", "items": [1, 2]}
    assert attempt.parsed_output_selected is True


def test_mixed_json_and_text_validators_select_parsed_output_but_run_text_on_raw() -> None:
    raw_check = RecordsRawCheck()
    candidate = 'marker text before JSON {"title": "Accepted", "items": []}'

    attempt = validate_candidate(
        candidate,
        validators=[
            JsonRequired(keys=["title", "items"]),
            ContainsPhrase("marker text"),
            raw_check,
        ],
    )

    assert attempt.ok is True
    assert attempt.output == {"title": "Accepted", "items": []}
    assert attempt.parsed_output_selected is True
    assert raw_check.seen == candidate


def test_gate_preserves_raw_output_when_no_json_validator_requires_parsed_data() -> None:
    candidate = '{"title": "Accepted"}'

    attempt = validate_candidate(candidate, validators=[ContainsPhrase("Accepted")])

    assert attempt.ok is True
    assert attempt.extraction.parsed_available is True
    assert attempt.output == candidate
    assert attempt.parsed_output_selected is False


def test_gate_report_payloads_are_json_stable_and_written_to_artifacts(
    tmp_path: Path,
    assert_json_stable: Callable[[Any], Any],
) -> None:
    report = build_validation_report(
        ['text before {"title": "Accepted"}'],
        validators=[JsonRequired(keys=["title"])],
        artifact_root=tmp_path,
        stage="summarize",
    )

    assert isinstance(report, GateReport)
    assert report.ok is True
    assert report.output == {"title": "Accepted"}
    payload = assert_json_stable(report.to_dict())
    assert payload["attempt_count"] == 1
    assert payload["validation_results"][0]["parsed_json_required"] is True
    assert payload["attempts"][0]["extraction"]["metadata"]["json_source"] == "embedded_text"
    assert (tmp_path / "validation_report_attempt_0.json").is_file()
    assert (tmp_path / "validation_report.json").is_file()
    assert {artifact.name for artifact in report.artifacts} == {
        "validation_report_attempt_0.json",
        "validation_report.json",
    }


def test_exhausted_invalid_json_fails_gracefully_with_diagnostics_and_best_output() -> None:
    result = run_validation_pipeline(
        ["not json", "still not json"],
        validators=[NoMarkdownFences(), JsonRequired(keys=["must_exist"])],
        max_attempts=2,
    )

    assert isinstance(result, TaskResult)
    assert result.ok is False
    assert result.output is None
    assert result.best_output == "still not json"
    assert result.attempt_count == 2
    assert {diagnostic.code for diagnostic in result.diagnostics} >= {
        "validation.json_invalid",
        "validation.exhausted",
    }


def test_exhausted_report_exposes_remediation_feedback_and_best_parsed_candidate() -> None:
    report = build_validation_report(
        ['{"title": "Almost accepted"}'],
        validators=[JsonRequired(keys=["title", "must_exist"])],
    )

    assert report.ok is False
    assert report.best_output == {"title": "Almost accepted"}
    assert report.remediation_feedback[0].messages == ("Missing required JSON key(s): must_exist",)
    assert report.to_task_result().best_output == {"title": "Almost accepted"}
