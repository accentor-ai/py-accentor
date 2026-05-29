"""Focused example: redact before dispatch, validate after dispatch.

General purpose:
    Show how Accentor can place deterministic privacy controls around an
    agentic support draft. Sensitive input is transformed before dispatch, and
    generated output is checked before it can leave the workflow.

Toy setting:
    A customer note contains obvious PII-like tokens: email, phone, account ID,
    and amount. Regex redaction is intentionally simple so the example focuses
    on the boundary pattern rather than on complete privacy detection.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from accentor.core.decorators import stage, workflow
from accentor.dispatch.agents.providers.codex_cli import CodexCli
from accentor.evaluate.validation import (
    ContainsPhrase,
    ForbiddenPattern,
    JsonRequired,
    NoMarkdownFences,
)


CUSTOMER_NOTE = """
Hi, this is regarding account ACC-90412. My email is dana.park@example.com and
you can also reach me at 555-012-3456. I was charged twice for the same order
last week. The second charge is $47.50. Please help.
"""

PII_PATTERNS = [
    (re.compile(r"\S+@\S+\.\S+"), "[EMAIL]", "email addresses"),
    (re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"), "[PHONE]", "phone numbers"),
    (re.compile(r"\bACC-\d+\b"), "[ACCOUNT]", "internal account identifiers"),
    (re.compile(r"\$\d+\.\d{2}"), "[AMOUNT]", "exact dollar amounts"),
]


@stage(name="redact_note")
def redact_note(raw_note: str) -> str:
    # This local stage is deliberately conventional code. It reduces what the
    # agent can see before any prompt is built.
    redacted = raw_note
    for pattern, token, _label in PII_PATTERNS:
        redacted = pattern.sub(token, redacted)
    return redacted


# The agent receives the redacted note only. Validators then catch obvious PII
# patterns that might be repeated, guessed, or invented in the generated reply.
@stage(
    name="draft_safe_response",
    agent=CodexCli(sandbox="read-only"),
    validators=[
        NoMarkdownFences(),
        JsonRequired(keys=["reply"]),
        ForbiddenPattern(r"\S+@\S+\.\S+", "email addresses"),
        ForbiddenPattern(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "phone numbers"),
        ForbiddenPattern(r"\bACC-\d+\b", "internal account identifiers"),
        ForbiddenPattern(r"\$\d+\.\d{2}", "exact dollar amounts"),
        # Privacy-safe is not enough; the reply also has to address the user's
        # actual issue in this toy setting.
        ContainsPhrase(field="reply", phrase="duplicate charge"),
    ],
    max_attempts=2,
    inject_criteria=True,
)
def draft_safe_response(
    redacted_note: str,
    success_criteria: str = "",
) -> str:
    return f"""
    Draft a helpful customer support reply to this redacted note. The reply
    must not include any personal information, account IDs, or exact dollar
    amounts. Return JSON only.

    {success_criteria}

    Redacted customer note:
    {redacted_note}
    """


@workflow(name="pii_filtered_support_reply")
def pii_filtered_support_reply() -> dict:
    # The workflow makes the privacy handoff explicit: raw input goes only to
    # the redaction stage, and the agentic stage receives the sanitized version.
    redacted = redact_note(CUSTOMER_NOTE)
    return draft_safe_response(redacted)


def _separator(label: str = "") -> None:
    if label:
        print(f"\n{'─' * 20} {label} {'─' * 20}")
    else:
        print(f"{'─' * 60}")


def _print_result(result) -> None:
    _separator("WORKFLOW: pii_filtered_support_reply")

    print(f"Status   : {'PASS' if result.ok else 'FAIL'}")
    print(f"Attempts : {result.attempt_count}")

    redacted = redact_note(CUSTOMER_NOTE)
    subs = sum(len(pat.findall(CUSTOMER_NOTE)) for pat, _, _ in PII_PATTERNS)
    _separator("REDACTION")
    print(f"  Substitutions: {subs}")
    for pat, token, label in PII_PATTERNS:
        count = len(pat.findall(CUSTOMER_NOTE))
        if count:
            print(f"    {token:12s} {count} {label}")
    print(f"\n  Redacted input:\n    {redacted.strip()}")

    validators = draft_safe_response.__accentor_stage_config__.validators
    _separator("VALIDATORS ({} registered)".format(len(validators)))
    for v in validators:
        desc = v.criteria_description if hasattr(v, "criteria_description") else ""
        print(f"  {type(v).__name__:25s} {desc}")

    if result.diagnostics:
        _separator("DIAGNOSTICS")
        for d in result.diagnostics:
            severity = d.severity.upper()
            source = f" (source: {d.source})" if d.source else ""
            print(f"  [{severity}] {d.code}{source}")
            print(f"           {d.message}")
            if d.hint:
                print(f"           hint: {d.hint}")

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
    result = pii_filtered_support_reply()
    _print_result(result)
