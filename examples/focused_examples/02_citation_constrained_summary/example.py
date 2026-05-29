"""Focused example: source-derived constraints around agentic prose.

General purpose:
    Show how validators can be built from the same source material given to the
    agent. The agent writes the executive summary, but deterministic checks
    reject claims that introduce unsupported numbers or omit source labels.

Toy setting:
    Two tiny quarterly-performance excerpts stand in for a real evidence pack.
    The example derives a numeric allowlist from those excerpts and requires the
    accepted JSON to keep citations visible.
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
    ArrayLength,
    ContainsPhrase,
    ExactPhraseCount,
    ForbiddenPattern,
    JsonRequired,
    NoMarkdownFences,
    Validator,
)


SOURCE_A = """
[Source: logistics-q3]
Average fulfillment time increased from 2.1 days to 3.4 days between July and
September. The primary bottleneck was warehouse consolidation in the midwest
region, which reduced same-day dispatch capacity by 40 percent.
"""

SOURCE_B = """
[Source: cx-survey-q3]
Customer satisfaction for delivery speed dropped from 87 percent to 71 percent
in the same quarter. Free-text responses frequently mention "slow shipping" and
"no tracking updates." The NPS score for logistics fell 12 points.
"""

NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")


def extract_numbers(*sources: str) -> set[str]:
    # In production this could be a richer extractor that preserves units,
    # source spans, and table coordinates. Here a regex keeps the idea visible.
    return set(NUMBER_PATTERN.findall("\n".join(sources)))


ALLOWED_NUMBERS = extract_numbers(SOURCE_A, SOURCE_B)


class NumbersFromSources(Validator):
    """Reject agent output that introduces numbers not present in the sources."""

    def __init__(self, allowed: set[str]) -> None:
        self.allowed = allowed

    def check(self, output: str) -> list[str]:
        # The validator compares numbers found in the model output with numbers
        # found in the source excerpts before the agent ran.
        found = set(NUMBER_PATTERN.findall(output))
        invented = found - self.allowed
        return [f"Number not in source material: {n}" for n in sorted(invented)]


# This stage demonstrates evidence-bound generation: prose is allowed, but only
# after source labels, JSON shape, and source-derived numeric constraints pass.
@stage(
    name="summarize_with_citations",
    agent=CodexCli(sandbox="read-only"),
    validators=[
        NoMarkdownFences(),
        JsonRequired(keys=["title", "findings", "sources_used"]),
        ContainsPhrase(field="findings", phrase="logistics-q3"),
        ContainsPhrase(field="findings", phrase="cx-survey-q3"),
        ArrayLength(field="sources_used", exactly=2),
        # A deliberately narrow content check shows how local policy can be
        # layered on top of generic JSON and citation requirements.
        ExactPhraseCount(field="findings", phrase="NPS", count=1),
        ForbiddenPattern(r"\b[A-Z]{2,10}-\d+\b", "internal ticket IDs"),
        ForbiddenPattern(r"\S+@\S+\.\S+", "email addresses"),
        NumbersFromSources(allowed=ALLOWED_NUMBERS),
    ],
    max_attempts=2,
    inject_criteria=True,
)
def summarize_with_citations(
    source_a: str,
    source_b: str,
    success_criteria: str = "",
) -> str:
    return f"""
    Write a concise executive summary of these two source excerpts about
    quarterly shipping performance. Return JSON only.

    {success_criteria}

    {source_a}

    {source_b}
    """


@workflow(name="citation_constrained_summary")
def citation_constrained_summary() -> dict:
    # The workflow passes both sources to the agentic stage. The same inputs also
    # feed the deterministic validator setup above.
    return summarize_with_citations(SOURCE_A, SOURCE_B)


def _separator(label: str = "") -> None:
    if label:
        print(f"\n{'─' * 20} {label} {'─' * 20}")
    else:
        print(f"{'─' * 60}")


def _print_result(result) -> None:
    _separator("WORKFLOW: citation_constrained_summary")

    print(f"Status   : {'PASS' if result.ok else 'FAIL'}")
    print(f"Attempts : {result.attempt_count}")

    print(f"\nAllowed numbers derived from sources: {sorted(ALLOWED_NUMBERS)}")

    validators = summarize_with_citations.__accentor_stage_config__.validators
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
    result = citation_constrained_summary()
    _print_result(result)
