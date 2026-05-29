from __future__ import annotations

import json

from accentor.configure.prompt import (
    PromptCompiler,
    build_success_criteria_text,
    criteria_text,
)
from accentor.evaluate.validation import JsonRequired, NoMarkdownFences, ValidationResult
from accentor.record.observe import REDACTED_VALUE


def test_prompt_source_defaults_to_function_return_value() -> None:
    def prompt(issue_text: str) -> str:
        return f"Summarize this issue: {issue_text}"

    compiled = PromptCompiler().compile(prompt, args=("blank plan names",))

    assert compiled.prompt == "Summarize this issue: blank plan names"
    assert compiled.sections == ()


def test_success_criteria_block_is_injected_into_declared_parameter() -> None:
    def prompt(success_criteria: str = "") -> str:
        return f"Return only JSON.\n\n{success_criteria}"

    compiled = PromptCompiler(
        validators=[
            NoMarkdownFences(),
            JsonRequired(keys=["title"]),
        ],
        inject_criteria=True,
    ).compile(prompt)

    assert compiled.prompt == (
        "Return only JSON.\n\n"
        "Success criteria:\n"
        "- NoMarkdownFences\n"
        "- JsonRequired(keys=['title'])"
    )
    assert [section.name for section in compiled.sections] == ["success_criteria"]
    assert compiled.injected_parameters["success_criteria"].startswith("Success criteria:")


def test_previous_validation_failures_are_appended_for_retry_feedback() -> None:
    def prompt(success_criteria: str = "") -> str:
        return success_criteria

    previous = ValidationResult.failure(
        [
            "Missing required JSON key(s): must_exist",
            "Output must not contain Markdown code fences.",
        ],
        validator="JsonRequired",
    )

    compiled = PromptCompiler(
        validators=[JsonRequired(keys=["must_exist"])],
        inject_criteria=True,
    ).compile(prompt, previous_validation_results=[previous])

    assert compiled.prompt == (
        "Success criteria:\n"
        "- JsonRequired(keys=['must_exist'])\n\n"
        "Previous validation failures:\n"
        "- Missing required JSON key(s): must_exist\n"
        "- Output must not contain Markdown code fences."
    )
    assert [section.name for section in compiled.sections] == [
        "success_criteria",
        "previous_validation_failures",
    ]


def test_template_placeholder_injection_is_targeted_only() -> None:
    compiled = PromptCompiler(
        validators=[JsonRequired(keys=["title"])],
        inject_criteria=True,
    ).compile("Write for {audience}.\n{success_criteria}")

    assert compiled.prompt == (
        "Write for {audience}.\n"
        "Success criteria:\n"
        "- JsonRequired(keys=['title'])"
    )
    assert compiled.placeholder_replacements == ("success_criteria",)


def test_prompt_section_redaction_hides_raw_prompt_and_sensitive_criteria() -> None:
    class SecretBackedValidator:
        def __init__(self) -> None:
            self.visible_rule = "return JSON"
            self.secret_ref = "verifier-token-123"
            self._raw_secret = "hidden-verifier-secret"

    def prompt(success_criteria: str = "") -> str:
        return f"Use this verifier-backed rule.\n{success_criteria}"

    compiled = PromptCompiler(
        validators=[SecretBackedValidator()],
        inject_criteria=True,
    ).compile(prompt)

    raw_payload = json.dumps(compiled.to_dict(), sort_keys=True)
    assert "verifier-token-123" not in raw_payload
    assert "hidden-verifier-secret" not in raw_payload
    assert REDACTED_VALUE in compiled.prompt

    redacted = compiled.redacted()
    assert redacted["prompt"] == REDACTED_VALUE
    assert redacted["sections"][0]["text"] == REDACTED_VALUE
    assert redacted["injected_parameters"]["success_criteria"] == REDACTED_VALUE


def test_no_injection_when_no_parameter_or_template_requests_it() -> None:
    def prompt() -> str:
        return "Return JSON with a title."

    compiled = PromptCompiler(
        validators=[JsonRequired(keys=["title"])],
        inject_criteria=True,
    ).compile(prompt)

    assert compiled.prompt == "Return JSON with a title."
    assert compiled.sections == ()
    assert compiled.injected_parameters == {}


def test_success_criteria_helpers_are_deterministic_and_safe() -> None:
    class CustomValidator:
        def __init__(self) -> None:
            self.labels = {"beta", "alpha"}
            self.secret_token = "raw-token"

    class ExplicitValidator:
        @property
        def criteria_description(self) -> str:
            return "Use the explicit visible criterion"

    first = build_success_criteria_text(validators=[CustomValidator()])
    second = build_success_criteria_text(validators=[CustomValidator()])

    assert first == second
    assert criteria_text(CustomValidator()) == (
        "CustomValidator(labels=['alpha', 'beta'], secret_token='[REDACTED]')"
    )
    assert criteria_text(ExplicitValidator()) == "Use the explicit visible criterion"
    assert "raw-token" not in first
