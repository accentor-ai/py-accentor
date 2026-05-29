"""Tutorial 03: Validators — deterministic checks without agents.

Part 1: Built-in validator catalog — every validator class with pass and fail.
Part 2: Custom validators — the check() contract, use_parsed_output, and
        when to subclass Validator vs. use a plain callable.
Part 3: Composition — all_of(), any_of(), not_(), and how composed validators
        report diagnostics.
Part 4: ValidationContext — how validators see raw text vs. parsed JSON, and
        how field-path validators navigate nested structures.
Part 5: criteria_description() — how Accentor tells agents what validators expect.
Part 6: What validators won't do (by design).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from accentor.evaluate.validation import (
    ArrayLength,
    ContainsPhrase,
    ExactPhraseCount,
    ForbiddenPattern,
    JsonFieldEquals,
    JsonRequired,
    NoMarkdownFences,
    TitleMaxWords,
    Validator,
    ValidationContext,
    ValidationResult,
    all_of,
    any_of,
    criteria_description,
    not_,
)


def show(name: str, validator, candidate: str) -> None:
    ctx = ValidationContext.from_candidate(candidate)
    result = validator.validate(candidate, ctx)
    status = "PASS" if result.ok else "FAIL"
    print(f"  {name}: {status}")
    for msg in result.messages:
        print(f"    -> {msg}")


# ---------------------------------------------------------------------------
# Part 1: Built-in validator catalog
# ---------------------------------------------------------------------------

GOOD = json.dumps({
    "title": "Fix CSV import",
    "summary": "Blank plan names cause customer impact during onboarding.",
    "risks": ["data loss", "user churn"],
    "tags": ["import", "csv"],
    "priority": "high",
})

BAD = json.dumps({
    "title": "This title is far too long and should definitely be rejected by the validator check",
    "summary": "Something broke.",
    "risks": ["one"],
    "tags": ["a", "b", "c"],
    "priority": "medium",
})


def part1_builtin_validators() -> None:
    print("=" * 60)
    print("PART 1: Built-in validator catalog")
    print("=" * 60)

    catalog = {
        "NoMarkdownFences":  (NoMarkdownFences(), "Rejects output with ```fences```"),
        "JsonRequired":      (JsonRequired(keys=["title", "summary", "risks"]), "Requires valid JSON with specific keys"),
        "TitleMaxWords":     (TitleMaxWords(field="title", max_words=5), "Limits word count in a field"),
        "ContainsPhrase":    (ContainsPhrase(field="summary", phrase="customer impact"), "Requires exact phrase"),
        "ExactPhraseCount":  (ExactPhraseCount(field="summary", phrase="impact", count=1), "Requires exact occurrence count"),
        "ArrayLength":       (ArrayLength(field="risks", exactly=2), "Constrains array length"),
        "JsonFieldEquals":   (JsonFieldEquals(field="priority", value="high"), "Requires field = value"),
        "ForbiddenPattern":  (ForbiddenPattern(r"\b[A-Z]{2,10}-\d+\b", "ticket IDs"), "Rejects regex matches"),
    }

    for name, (validator, desc) in catalog.items():
        print(f"\n  --- {name}: {desc} ---")
        show(f"good output", validator, GOOD)
        show(f"bad output", validator, BAD)

    # NoMarkdownFences with actual fences
    print(f"\n  --- NoMarkdownFences on fenced output ---")
    show("fenced", NoMarkdownFences(), '```json\n{"title": "Fix"}\n```')

    # ForbiddenPattern catching a ticket ID
    print(f"\n  --- ForbiddenPattern catching ticket ID ---")
    show("with ID", ForbiddenPattern(r"\b[A-Z]{2,10}-\d+\b", "ticket IDs"),
         json.dumps({"note": "See ENG-1234 for details."}))


# ---------------------------------------------------------------------------
# Part 2: Custom validators
# ---------------------------------------------------------------------------

class WordCountValidator(Validator):
    """Rejects output whose total word count exceeds a threshold."""

    description = "Total word count must be within limit."

    def __init__(self, max_words: int = 50):
        self.max_words = max_words

    def check(self, output):
        text = output if isinstance(output, str) else json.dumps(output)
        count = len(text.split())
        if count > self.max_words:
            return [f"Output has {count} words; maximum is {self.max_words}."]
        return []


class NumericRangeValidator(Validator):
    """Validates that a JSON field falls within a numeric range."""

    use_parsed_output = True

    def __init__(self, field: str, min_val: float, max_val: float):
        self.field = field
        self.min_val = min_val
        self.max_val = max_val
        self.description = f"{field} must be between {min_val} and {max_val}."

    def check(self, output):
        if not isinstance(output, dict):
            return [f"Expected a JSON object, got {type(output).__name__}."]
        value = output.get(self.field)
        if value is None:
            return [f"Missing field: {self.field}."]
        if not isinstance(value, (int, float)):
            return [f"Field {self.field} is not numeric: {value!r}."]
        if not (self.min_val <= value <= self.max_val):
            return [f"{self.field}={value}; must be between {self.min_val} and {self.max_val}."]
        return []


def part2_custom_validators() -> None:
    print("\n" + "=" * 60)
    print("PART 2: Custom validators")
    print("=" * 60)

    # check(output) -> list[str]: return error messages, empty = pass.
    wc = WordCountValidator(max_words=10)
    show("short text", wc, "This is fine.")
    show("long text", wc, "This text has way more than ten words and should be rejected by the validator.")

    # use_parsed_output=True: check() receives parsed Python dict, not raw text.
    nr = NumericRangeValidator("confidence", 0.0, 1.0)
    show("in range", nr, json.dumps({"confidence": 0.85}))
    show("out of range", nr, json.dumps({"confidence": 1.5}))
    show("missing field", nr, json.dumps({"other": "data"}))

    # Plain callable as a validator — simplest form.
    def no_exclamation(output: str) -> list[str]:
        if "!" in str(output):
            return ["Output contains exclamation marks."]
        return []

    print(f"\n  --- Callable validator ---")
    # Callable validators work with all_of/any_of but don't have criteria_description.
    composed = all_of(no_exclamation)
    ctx = ValidationContext.from_candidate("Hello world")
    result = composed.validate("Hello world", ctx)
    print(f"  'Hello world': {'PASS' if result.ok else 'FAIL'}")
    ctx = ValidationContext.from_candidate("Hello world!")
    result = composed.validate("Hello world!", ctx)
    print(f"  'Hello world!': {'PASS' if result.ok else 'FAIL'}")


# ---------------------------------------------------------------------------
# Part 3: Composition
# ---------------------------------------------------------------------------

def part3_composition() -> None:
    print("\n" + "=" * 60)
    print("PART 3: Validator composition — all_of, any_of, not_")
    print("=" * 60)

    # all_of: every validator must pass.
    strict = all_of(
        NoMarkdownFences(),
        JsonRequired(keys=["title", "summary"]),
        TitleMaxWords(field="title", max_words=5),
    )

    print(f"\n  --- all_of (all must pass) ---")
    show("good", strict, GOOD)
    show("bad", strict, BAD)

    # any_of: at least one validator must pass.
    flexible = any_of(
        JsonFieldEquals(field="priority", value="high"),
        JsonFieldEquals(field="priority", value="critical"),
    )

    print(f"\n  --- any_of (at least one passes) ---")
    show("high priority", flexible, json.dumps({"priority": "high"}))
    show("critical priority", flexible, json.dumps({"priority": "critical"}))
    show("low priority", flexible, json.dumps({"priority": "low"}))

    # not_: inverts a validator.
    no_markdown = not_(NoMarkdownFences())
    print(f"\n  --- not_ (inverts result) ---")
    print(f"  not_(NoMarkdownFences) expects fences to be PRESENT:")
    show("plain text", no_markdown, '{"title": "Fix"}')
    show("fenced text", no_markdown, '```json\n{"title": "Fix"}\n```')

    # Nested composition: diagnostics bubble up from children.
    nested = all_of(
        NoMarkdownFences(),
        any_of(
            JsonFieldEquals(field="status", value="accepted"),
            JsonFieldEquals(field="status", value="reviewed"),
        ),
    )
    print(f"\n  --- Nested composition ---")
    show("accepted", nested, json.dumps({"status": "accepted"}))
    show("pending", nested, json.dumps({"status": "pending"}))


# ---------------------------------------------------------------------------
# Part 4: ValidationContext
# ---------------------------------------------------------------------------

def part4_context() -> None:
    print("\n" + "=" * 60)
    print("PART 4: ValidationContext — raw vs. parsed")
    print("=" * 60)

    raw_json_string = '{"title": "Fix CSV", "count": 3}'
    ctx = ValidationContext.from_candidate(raw_json_string)

    print(f"\n  --- Context from JSON string ---")
    print(f"  raw_text:         {ctx.raw_text!r}")
    print(f"  parsed_available: {ctx.parsed_available}")
    print(f"  parsed_candidate: {ctx.parsed_candidate}")

    # Non-JSON text: parsed_available is False.
    plain = ValidationContext.from_candidate("just plain text")
    print(f"\n  --- Context from plain text ---")
    print(f"  raw_text:         {plain.raw_text!r}")
    print(f"  parsed_available: {plain.parsed_available}")
    print(f"  json_error:       {plain.json_error!r}")

    # Field-path validators navigate into parsed JSON.
    nested_json = json.dumps({
        "metadata": {"tags": ["csv", "import", "fix"]},
        "title": "Short",
    })
    print(f"\n  --- Field-path access ---")
    show("metadata.tags length", ArrayLength(field="metadata.tags", min_length=2), nested_json)
    show("title max words", TitleMaxWords(field="title", max_words=3), nested_json)


# ---------------------------------------------------------------------------
# Part 5: criteria_description
# ---------------------------------------------------------------------------

def part5_criteria() -> None:
    print("\n" + "=" * 60)
    print("PART 5: criteria_description() — what agents see")
    print("=" * 60)

    # When inject_criteria=True, Accentor tells the agent what validators expect.
    # criteria_description() produces the text that gets injected.

    validators = [
        NoMarkdownFences(),
        JsonRequired(keys=["title", "summary", "risks"]),
        TitleMaxWords(field="title", max_words=10),
        ArrayLength(field="risks", exactly=2),
        ForbiddenPattern(r"\b[A-Z]{2,10}-\d+\b", "ticket IDs"),
        WordCountValidator(max_words=50),
    ]

    print(f"\n  Criteria descriptions (injected into prompts):")
    for v in validators:
        print(f"  - {criteria_description(v)}")


# ---------------------------------------------------------------------------
# Part 6: What validators won't do
# ---------------------------------------------------------------------------

def part6_boundaries() -> None:
    print("\n" + "=" * 60)
    print("PART 6: What validators won't do (by design)")
    print("=" * 60)

    print("""
    Validators:
    - Will NOT call an LLM. All validation is deterministic local Python.
      There is no "semantic similarity" or "model-judged quality" validator.
    - Will NOT modify output. They inspect and report; extraction is separate.
    - Will NOT short-circuit other validators. all_of() runs every validator
      even after the first failure, so diagnostics are complete.
    - Will NOT validate file contents unless you use file validators
      (RequiredFile, FileRequiredKeys, ExactMatch) with an artifact_root.
    - Will NOT enforce constraints the agent can't see. Use inject_criteria=True
      so the agent knows what validators expect before writing.
    - Will NOT validate Pydantic models, pandas DataFrames, or code quality.
      Those are [U] stubs — reserved names, not supported behavior.
    """)


if __name__ == "__main__":
    part1_builtin_validators()
    part2_custom_validators()
    part3_composition()
    part4_context()
    part5_criteria()
    part6_boundaries()
