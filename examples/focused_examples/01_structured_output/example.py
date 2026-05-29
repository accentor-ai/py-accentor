"""Focused example: agent output accepted only after structured validation.

General purpose:
    Show how Accentor can turn an agent's free-form writing ability into a
    bounded application object. The agent drafts the content, but deterministic
    validators decide whether the result is safe to treat as data.

Toy setting:
    A short product issue is summarized for a product manager. The example is
    intentionally small so the validation boundary is easy to see: JSON shape,
    field lengths, required wording, and forbidden internal ticket IDs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from accentor.core.decorators import stage, workflow
from accentor.dispatch.agents.providers.codex_cli import CodexCli
from accentor.evaluate.validation import (
    ArrayLength,
    ContainsPhrase,
    ForbiddenPattern,
    JsonRequired,
    NoMarkdownFences,
    TitleMaxWords,
)


ISSUE_TEXT = """
Customer onboarding stalls when imported CSV files contain blank plan names.
Support reports that users see a generic failure message and retry the same
upload several times. The product team needs a concise triage summary.
"""


# This stage is the agentic boundary: the prompt asks for useful writing, while
# the validators below define the contract that accepted writing must satisfy.
@stage(
    name="summarize_issue",
    agent=CodexCli(sandbox="read-only"),
    validators=[
        # Start with format gates so the caller receives machine-readable data,
        # not a Markdown snippet that merely looks like JSON.
        NoMarkdownFences(),
        JsonRequired(keys=["title", "summary", "risks", "next_steps"]),
        # Then apply product-specific checks that make the toy output useful to
        # downstream code and dashboards.
        TitleMaxWords(field="title", max_words=10),
        ContainsPhrase(field="summary", phrase="customer impact"),
        ArrayLength(field="risks", exactly=2),
        ArrayLength(field="next_steps", exactly=3),
        # The example also blocks accidental leakage of internal identifiers.
        ForbiddenPattern(r"\b[A-Z]{2,10}-\d+\b", "internal ticket IDs"),
    ],
    max_attempts=2,
    # Accentor can inject validator criteria into the prompt and remediation
    # attempts, keeping the prompt aligned with the acceptance contract.
    inject_criteria=True,
)
def summarize_issue(issue_text: str, success_criteria: str = "") -> str:
    return f"""
    Summarize this product issue for a busy product manager.

    {success_criteria}

    Issue:
    {issue_text}
    """


@workflow(name="issue_summary_review")
def issue_summary_review() -> dict:
    # The workflow stays ordinary Python: collect inputs, call the staged agent
    # boundary, and let the stage return a validated object or diagnostics.
    return summarize_issue(ISSUE_TEXT)


def _separator(label: str = "") -> None:
    if label:
        print(f"\n{'─' * 20} {label} {'─' * 20}")
    else:
        print(f"{'─' * 60}")


def _print_result(result) -> None:
    _separator("WORKFLOW: issue_summary_review")

    print(f"Status   : {'PASS' if result.ok else 'FAIL'}")
    print(f"Attempts : {result.attempt_count}")

    validators = summarize_issue.__accentor_stage_config__.validators
    _separator("VALIDATORS ({} registered)".format(len(validators)))
    for v in validators:
        desc = v.criteria_description if hasattr(v, "criteria_description") else ""
        print(f"  {type(v).__name__:25s} {desc}")

    if result.diagnostics:
        _separator("DIAGNOSTICS")
        for d in result.diagnostics:
            severity = d.severity.upper()
            source = f" ({d.source})" if d.source else ""
            print(f"  [{severity}] {d.code}{source}: {d.message}")
            if d.hint:
                print(f"         hint: {d.hint}")

    if result.events:
        _separator("EVENTS ({} recorded)".format(len(result.events)))
        for e in result.events:
            ts = e.timestamp.split("T")[1][:12] if "T" in e.timestamp else e.timestamp
            label = e.stage or e.workflow or ""
            status = e.status or ""
            print(f"  {ts}  {e.event_type:25s} {label:30s} {status}")

    _separator("OUTPUT")
    if result.ok:
        print(json.dumps(result.output, indent=2))
    else:
        print("(best-effort output, did not pass validation)")
        print(result.best_output)

    _separator()


if __name__ == "__main__":
    result = issue_summary_review()
    _print_result(result)
