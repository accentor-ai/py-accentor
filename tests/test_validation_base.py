from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from accentor.core.task.diagnostics import Diagnostic
from accentor.evaluate.validation import (
    ValidationContext,
    ValidationResult,
    Validator,
    all_of,
    any_of,
    criteria_description,
    not_,
    validator_slug,
)


def assert_json_stable(payload: dict) -> dict:
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    decoded = json.loads(encoded)
    assert json.dumps(decoded, allow_nan=False, sort_keys=True) == encoded
    return decoded


class RejectPhrase(Validator):
    def __init__(self, phrase: str, *, description: str | None = None) -> None:
        self.phrase = phrase
        if description is not None:
            self.criteria_description = description

    def check(self, output: str) -> list[str]:
        if self.phrase in output:
            return [f"Output contains forbidden phrase: {self.phrase}"]
        return []


class AlwaysPass(Validator):
    def check(self, output: Any) -> list[str]:
        return []


class AlwaysFail(Validator):
    def __init__(self, message: str) -> None:
        self.message = message

    def check(self, output: Any) -> list[str]:
        return [self.message]


def test_validation_context_preserves_raw_and_parsed_candidates(tmp_path: Path) -> None:
    diagnostic = Diagnostic.info("extract.json", "Parsed JSON candidate.", source="extractor")
    context = ValidationContext.from_candidate(
        '{"answer": 42}',
        parsed_candidate={"answer": 42},
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspace",
        metadata={"attempt": 0},
        diagnostics=[diagnostic],
    )

    assert context.raw == '{"answer": 42}'
    assert context.parsed == {"answer": 42}
    assert context.parsed_available is True
    assert context.artifact_root == tmp_path / "artifacts"
    assert context.diagnostics == (diagnostic,)

    payload = assert_json_stable(context.to_dict())
    assert payload["parsed_candidate"] == {"answer": 42}
    assert payload["metadata"] == {"attempt": 0}


def test_validation_result_normalizes_messages_errors_and_report_payload() -> None:
    child = ValidationResult.success(validator="Child", criteria="Child")
    result = ValidationResult.failure(
        "Missing field: title",
        validator="JsonRequired",
        criteria="JsonRequired(keys=['title'])",
        metadata={"path": ["title"]},
        children=[child],
    )

    assert result.ok is False
    assert result.messages == ("Missing field: title",)
    assert result.errors == result.messages
    assert result.diagnostics[0].code == "validation.failed"
    assert result.diagnostics[0].source == "JsonRequired"
    direct = ValidationResult(False, messages="Direct failure", validator="Direct")
    assert direct.errors == ("Direct failure",)
    assert direct.diagnostics[0].source == "Direct"

    payload = assert_json_stable(result.to_dict())
    assert payload["ok"] is False
    assert payload["messages"] == ["Missing field: title"]
    assert payload["errors"] == ["Missing field: title"]
    assert payload["validator"] == "JsonRequired"
    assert payload["criteria"] == "JsonRequired(keys=['title'])"
    assert payload["metadata"] == {"path": ["title"]}
    assert payload["children"][0]["ok"] is True


def test_validator_validate_adapts_custom_check_and_returns_failure_messages() -> None:
    validator = RejectPhrase("secret")

    accepted = validator.validate("public text")
    rejected = validator.validate("contains secret value")

    assert accepted.ok is True
    assert accepted.criteria == "RejectPhrase(phrase='secret')"
    assert rejected.ok is False
    assert rejected.messages == ("Output contains forbidden phrase: secret",)


def test_custom_check_receives_raw_text_by_default_with_parsed_opt_in() -> None:
    class RecordsInput(Validator):
        def __init__(self) -> None:
            self.seen: Any = None

        def check(self, output: Any) -> list[str]:
            self.seen = output
            return []

    class ParsedRecordsInput(RecordsInput):
        use_parsed_candidate = True

    context = ValidationContext.from_candidate('{"answer": 42}', parsed_candidate={"answer": 42})
    raw_validator = RecordsInput()
    parsed_validator = ParsedRecordsInput()

    assert raw_validator.validate({"answer": 42}, context).ok is True
    assert parsed_validator.validate('{"answer": 42}', context).ok is True
    assert raw_validator.seen == '{"answer": 42}'
    assert parsed_validator.seen == {"answer": 42}


def test_validator_validate_converts_check_exceptions_to_failed_results() -> None:
    class BrokenValidator(Validator):
        def check(self, output: Any) -> list[str]:
            raise ValueError("bad rule")

    result = BrokenValidator().validate("candidate")

    assert result.ok is False
    assert result.diagnostics[0].code == "validation.validator_error"
    assert "bad rule" in result.messages[0]


def test_criteria_description_uses_explicit_or_public_config_deterministically() -> None:
    class Configured(Validator):
        def __init__(self) -> None:
            self.limit = 3
            self.labels = {"beta", "alpha"}
            self._secret = "hidden"

    explicit = RejectPhrase("secret", description="Must not contain secret")

    assert criteria_description(explicit) == "Must not contain secret"
    assert criteria_description(Configured()) == "Configured(labels=['alpha', 'beta'], limit=3)"
    assert validator_slug("JsonFieldEquals") == "json_field_equals"


def test_all_of_aggregates_all_child_failures() -> None:
    validator = all_of(AlwaysFail("first failed"), AlwaysPass(), AlwaysFail("second failed"))

    result = validator.validate("candidate")

    assert result.ok is False
    assert result.messages == ("first failed", "second failed")
    assert len(result.children) == 3
    assert [child.ok for child in result.children] == [False, True, False]


def test_any_of_succeeds_when_one_child_succeeds_and_reports_all_failures_otherwise() -> None:
    accepted = any_of(AlwaysFail("first failed"), AlwaysPass())
    rejected = any_of([AlwaysFail("first failed"), AlwaysFail("second failed")])

    accepted_result = accepted.validate("candidate")
    rejected_result = rejected.validate("candidate")

    assert accepted_result.ok is True
    assert accepted_result.messages == ()
    assert len(accepted_result.children) == 2
    assert rejected_result.ok is False
    assert rejected_result.messages == ("first failed", "second failed")


def test_not_inverts_child_validator() -> None:
    forbidden = not_(AlwaysPass(), description="Child must not pass")
    allowed = not_(AlwaysFail("expected failure"))

    forbidden_result = forbidden.validate("candidate")
    allowed_result = allowed.validate("candidate")

    assert forbidden_result.ok is False
    assert forbidden_result.messages == ("Negated validator passed: AlwaysPass",)
    assert allowed_result.ok is True
    assert len(forbidden_result.children) == 1


def test_validation_package_exports_base_api() -> None:
    from accentor.evaluate.validation import ValidationContext as ExportedContext
    from accentor.evaluate.validation import Validator as ExportedValidator

    assert ExportedContext is ValidationContext
    assert ExportedValidator is Validator
