from __future__ import annotations

import json

from accentor.evaluate import validation
from accentor.evaluate.validation import (
    ArrayLength,
    ContainsPhrase,
    ExactFinalMessage,
    ExactPhraseCount,
    ForbiddenPattern,
    JsonFieldEquals,
    JsonRequired,
    NoMarkdownFences,
    RequiredKeys,
    TitleMaxWords,
    ValidationContext,
)


P0_02_OUTPUT = """
{
  "title": "CSV Import Blank Plan Names",
  "summary": "Blank plan names create customer impact during onboarding.",
  "risks": ["Repeated upload retries", "Support escalation volume"],
  "next_steps": ["Improve validation copy", "Document required fields", "Track missing plan names"]
}
"""


def test_p0_02_mock_output_passes_listed_json_and_text_validators() -> None:
    validators = [
        NoMarkdownFences(),
        JsonRequired(keys=["title", "summary", "risks", "next_steps"]),
        TitleMaxWords(field="title", max_words=10),
        ContainsPhrase(field="summary", phrase="customer impact"),
        ArrayLength(field="risks", exactly=2),
        ArrayLength(field="next_steps", exactly=3),
        ForbiddenPattern(r"\b[A-Z]{2,10}-\d+\b", "internal ticket IDs"),
    ]

    results = [validator.validate(P0_02_OUTPUT) for validator in validators]

    assert [result.ok for result in results] == [True] * len(validators)


def test_json_required_rejects_unparseable_text_without_losing_raw_candidate() -> None:
    context = ValidationContext.from_candidate("not json")

    result = JsonRequired(keys=["must_exist"]).validate("not json", context)

    assert result.ok is False
    assert result.parsed_json_required is True
    assert "not valid JSON" in result.messages[0]
    assert context.raw_text == "not json"
    assert context.has_parsed_json is False


def test_json_required_accepts_root_keys_and_reports_missing_keys() -> None:
    accepted = JsonRequired(keys=["title", "items"]).validate('{"title": "ok", "items": []}')
    rejected = JsonRequired(keys=["title", "items"]).validate('{"title": "ok"}')

    assert accepted.ok is True
    assert rejected.ok is False
    assert rejected.messages == ("Missing required JSON key(s): items",)


def test_json_field_equals_checks_nested_paths() -> None:
    candidate = {"route": {"name": "technical", "confidence": 1}}

    accepted = JsonFieldEquals(field="route.name", value="technical").validate(candidate)
    rejected = JsonFieldEquals(field="route.name", value="billing").validate(candidate)

    assert accepted.ok is True
    assert rejected.ok is False
    assert "must equal" in rejected.messages[0]


def test_required_keys_checks_root_nested_object_and_json_file(tmp_path) -> None:
    candidate = {"root": {"answer": 42, "evidence": "fixture"}}
    file_path = tmp_path / "result.json"
    file_path.write_text(json.dumps({"paid_order_count": 2, "paid_total_amount": 57.5}), encoding="utf-8")

    root_result = RequiredKeys(keys=["root"]).validate(candidate)
    file_result = RequiredKeys(file_path, keys=["paid_order_count", "paid_total_amount"]).validate("")
    missing_result = RequiredKeys(keys=["missing"]).validate(candidate)

    assert root_result.ok is True
    assert file_result.ok is True
    assert missing_result.ok is False
    assert missing_result.messages == ("Missing required JSON key(s): missing",)


def test_array_length_supports_exact_min_and_max_constraints() -> None:
    candidate = {"items": [1, 2, 3]}

    assert ArrayLength(field="items", exactly=3).validate(candidate).ok is True
    assert ArrayLength(field="items", min_length=2, max_length=4).validate(candidate).ok is True
    rejected = ArrayLength(field="items", exactly=2).validate(candidate)

    assert rejected.ok is False
    assert rejected.messages == ("Array length was 3; expected 2.",)


def test_no_markdown_fences_rejects_fenced_text() -> None:
    assert NoMarkdownFences().validate('{"ok": true}').ok is True

    result = NoMarkdownFences().validate("```json\n{}\n```")

    assert result.ok is False
    assert result.messages == ("Output must not contain Markdown code fences.",)


def test_title_max_words_uses_raw_text_or_json_field() -> None:
    raw_result = TitleMaxWords(max_words=3).validate("short clear title")
    field_result = TitleMaxWords(field="title", max_words=4).validate('{"title": "short clear title"}')
    rejected = TitleMaxWords(field="title", max_words=2).validate('{"title": "too many words"}')

    assert raw_result.ok is True
    assert field_result.ok is True
    assert rejected.ok is False
    assert rejected.messages == ("Title has 3 words; expected at most 2.",)


def test_contains_phrase_and_exact_phrase_count_use_field_text() -> None:
    candidate = {"findings": "logistics-q3 cites NPS once."}

    assert ContainsPhrase(field="findings", phrase="LOGISTICS-Q3", case_sensitive=False).validate(candidate).ok is True
    assert ExactPhraseCount(field="findings", phrase="NPS", count=1).validate(candidate).ok is True

    rejected = ExactPhraseCount(field="findings", phrase="NPS", count=2).validate(candidate)

    assert rejected.ok is False
    assert rejected.messages == ("Phrase 'NPS' appeared 1 times; expected 2.",)


def test_forbidden_pattern_rejects_raw_or_field_matches() -> None:
    raw_rejected = ForbiddenPattern(r"\b[A-Z]{2,10}-\d+\b", "ticket IDs").validate("See ABC-123")
    field_rejected = ForbiddenPattern(r"\S+@\S+\.\S+", "emails", field="reply").validate(
        {"reply": "Email dana@example.com"}
    )

    assert raw_rejected.ok is False
    assert raw_rejected.messages == ("Text contains forbidden pattern: ticket IDs",)
    assert field_rejected.ok is False
    assert field_rejected.messages == ("Text contains forbidden pattern: emails",)


def test_exact_final_message_compares_raw_message_after_outer_strip() -> None:
    assert ExactFinalMessage("READY").validate("\nREADY\n").ok is True

    result = ExactFinalMessage("READY").validate("READY.")

    assert result.ok is False
    assert result.messages == ("Final message did not match expected text.",)


def test_validation_init_exports_supported_validators_without_unsupported_surfaces() -> None:
    assert validation.JsonRequired is JsonRequired
    assert validation.NoMarkdownFences is NoMarkdownFences
    assert validation.RequiredKeys is RequiredKeys
    assert not hasattr(validation, "JsonSchema")
    assert not hasattr(validation, "PydanticValidator")
    assert not hasattr(validation, "CodeValidator")
