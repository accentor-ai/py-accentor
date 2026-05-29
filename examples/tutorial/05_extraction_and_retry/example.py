"""Tutorial 05: Extraction and Retry — handling validation failure.

Part 1: JSON extraction — how Accentor finds JSON in agent text, and what
        happens when extraction fails.
Part 2: Retry with remediation — bad first response, diagnostics injected
        into the next attempt, successful recovery.
Part 3: Retry exhaustion — what happens when all attempts fail, and how
        best_output preserves the closest candidate.
Part 4: sequence() and retry() — composition helpers outside decorators.
Part 5: What extraction and retry won't do (by design).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from accentor.core.decorators import stage, workflow
from accentor.core.composition.sequencing import sequence, retry
from accentor.core.task.results import TaskResult
from accentor.dispatch.agents.providers.mock import MockAgent, mock_failure
from accentor.evaluate.validation import (
    ArrayLength,
    JsonRequired,
    NoMarkdownFences,
    TitleMaxWords,
    ValidationContext,
)
from accentor.evaluate.expose.extractors import JsonExtractor


# ---------------------------------------------------------------------------
# Part 1: JSON extraction
# ---------------------------------------------------------------------------

def part1_extraction() -> None:
    print("=" * 60)
    print("PART 1: JSON extraction — finding JSON in agent text")
    print("=" * 60)

    extractor = JsonExtractor()

    # Clean JSON string — trivial extraction.
    clean = '{"title": "Fix CSV", "risks": ["data loss"]}'
    result = extractor.extract(clean)
    print(f"\n  Clean JSON:")
    print(f"    raw:        {result.raw_candidate!r}")
    print(f"    parsed:     {result.parsed_candidate}")
    print(f"    has_parsed: {result.has_parsed}")

    # JSON inside markdown fences — extractor finds it.
    fenced = '```json\n{"title": "Fix CSV"}\n```'
    result = extractor.extract(fenced)
    print(f"\n  Fenced JSON:")
    print(f"    parsed:     {result.parsed_candidate}")
    print(f"    has_parsed: {result.has_parsed}")

    # JSON embedded in surrounding text — extractor locates the object.
    mixed = 'Here is the result:\n{"title": "Fix CSV", "count": 3}\nDone.'
    result = extractor.extract(mixed)
    print(f"\n  JSON embedded in text:")
    print(f"    parsed: {result.parsed_candidate}")

    # Plain text with no JSON — extraction produces diagnostics, not a crash.
    plain = "I could not generate the requested format."
    result = extractor.extract(plain)
    print(f"\n  No JSON found:")
    print(f"    has_parsed:  {result.has_parsed}")
    print(f"    parsed:      {result.parsed_candidate}")
    print(f"    diagnostics: {len(result.diagnostics)}")
    for d in result.diagnostics:
        print(f"      [{d.code}] {d.message}")

    # Already a Python dict — extractor passes it through.
    py_dict = {"title": "Already parsed"}
    result = extractor.extract(py_dict)
    print(f"\n  Python dict (already parsed):")
    print(f"    parsed: {result.parsed_candidate}")


# ---------------------------------------------------------------------------
# Part 2: Retry with remediation
# ---------------------------------------------------------------------------

def part2_retry_success() -> None:
    print("\n" + "=" * 60)
    print("PART 2: Retry — bad first response, successful second")
    print("=" * 60)

    bad_response = json.dumps({
        "title": "This title is way too long for the five-word validator to accept it",
        "risks": ["only one"],
    })

    good_response = json.dumps({
        "title": "CSV Import Fix",
        "summary": "Blank plan names cause failures.",
        "risks": ["data loss", "user churn"],
    })

    agent = MockAgent(responses=[bad_response, good_response])

    @stage(
        name="summarize_with_retry",
        agent=agent,
        validators=[
            NoMarkdownFences(),
            JsonRequired(keys=["title", "summary", "risks"]),
            TitleMaxWords(field="title", max_words=5),
            ArrayLength(field="risks", exactly=2),
        ],
        max_attempts=2,
        inject_criteria=True,
    )
    def summarize(issue: str, success_criteria: str = "") -> str:
        return f"Summarize:\n{success_criteria}\nIssue: {issue}"

    @workflow(name="retry_demo")
    def demo() -> dict:
        return summarize("CSV import fails on blank plan names.")

    result = demo()
    print(f"\n  ok:            {result.ok}")
    print(f"  attempt_count: {result.attempt_count}")
    print(f"  output:        {json.dumps(result.output, indent=2)}")

    # The second attempt's prompt includes failure diagnostics from attempt 1.
    if len(agent.requests) >= 2:
        prompt2 = agent.requests[1].prompt
        print(f"\n  Retry prompt includes prior failures:")
        for line in prompt2.splitlines():
            stripped = line.strip()
            if "fail" in stripped.lower() or "error" in stripped.lower() or "title" in stripped.lower():
                print(f"    {stripped}")

    print(f"\n  Events:")
    for event in result.events:
        print(f"    {event.event_type}: {event.stage or event.workflow or '-'}")


# ---------------------------------------------------------------------------
# Part 3: Retry exhaustion
# ---------------------------------------------------------------------------

def part3_exhaustion() -> None:
    print("\n" + "=" * 60)
    print("PART 3: Retry exhaustion — all attempts fail")
    print("=" * 60)

    bad1 = json.dumps({"title": "Way too long title that exceeds the limit"})
    bad2 = json.dumps({"title": "Still too long for the validator"})

    agent = MockAgent(responses=[bad1, bad2])

    @stage(
        name="always_fails",
        agent=agent,
        validators=[
            JsonRequired(keys=["title", "summary"]),
            TitleMaxWords(field="title", max_words=3),
        ],
        max_attempts=2,
        inject_criteria=True,
    )
    def always_fails(text: str, success_criteria: str = "") -> str:
        return f"Summarize:\n{success_criteria}\n{text}"

    @workflow(name="exhaustion_demo")
    def demo() -> dict:
        return always_fails("test")

    result = demo()
    print(f"\n  ok:            {result.ok}")
    print(f"  attempt_count: {result.attempt_count}")
    print(f"  output:        {result.output}")

    # best_output preserves the closest candidate even when all attempts fail.
    print(f"  best_output:   {result.best_output}")

    print(f"\n  All diagnostics:")
    for d in result.diagnostics:
        print(f"    [{d.severity}] {d.code}: {d.message}")


# ---------------------------------------------------------------------------
# Part 4: sequence() and retry() composition helpers
# ---------------------------------------------------------------------------

def part4_composition() -> None:
    print("\n" + "=" * 60)
    print("PART 4: sequence() and retry() — composition without decorators")
    print("=" * 60)

    # sequence() chains operations, passing output forward.
    def double(x):
        return x * 2

    def add_ten(x):
        return x + 10

    result = sequence([double, add_ten], initial_input=5)
    print(f"\n  sequence([double, add_ten], 5):")
    print(f"    ok:     {result.ok}")
    print(f"    output: {result.output}")

    # sequence() stops on failure when stop_on_failure=True (default).
    def always_fail(x):
        raise ValueError("cannot proceed")

    result = sequence([double, always_fail, add_ten], initial_input=5)
    print(f"\n  sequence with failure in middle:")
    print(f"    ok:          {result.ok}")
    print(f"    best_output: {result.best_output}")
    print(f"    diagnostic:  {result.diagnostics[0].code}")

    # retry() re-runs an operation up to max_attempts.
    call_count = 0

    def flaky_operation(x):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError(f"Attempt {call_count} failed")
        return x * 100

    result = retry(flaky_operation, max_attempts=5, name="flaky")
    print(f"\n  retry(flaky, max_attempts=5):")
    print(f"    ok:            {result.ok}")
    print(f"    output:        {result.output}")
    print(f"    attempt_count: {result.attempt_count}")

    # retry() with exhaustion.
    def never_works(x):
        raise ValueError("permanent failure")

    result = retry(never_works, max_attempts=3, name="never_works")
    print(f"\n  retry(never_works, max_attempts=3):")
    print(f"    ok:            {result.ok}")
    print(f"    attempt_count: {result.attempt_count}")
    print(f"    diagnostics:   {len(result.diagnostics)}")


# ---------------------------------------------------------------------------
# Part 5: What extraction/retry won't do
# ---------------------------------------------------------------------------

def part5_boundaries() -> None:
    print("\n" + "=" * 60)
    print("PART 5: What extraction and retry won't do")
    print("=" * 60)

    print("""
    Extraction:
    - Will NOT validate the extracted JSON. Extraction finds the data;
      validators decide if it's acceptable. These are separate steps.
    - Will NOT call the agent again if extraction fails. Extraction failure
      becomes a diagnostic; the retry loop decides whether to re-prompt.
    - Will NOT guess structure from partial JSON. If the JSON is malformed,
      extraction reports a parse failure and the raw text is preserved.

    Retry:
    - Will NOT change the agent or model between attempts. Same adapter,
      same validators, different prompt (with injected failure diagnostics).
    - Will NOT backtrack past the current stage. Retry is per-stage, not
      per-workflow. A failing stage retries its own attempts, then stops.
    - Will NOT retry indefinitely. max_attempts is a hard ceiling, not a
      suggestion. After exhaustion, the stage fails with complete diagnostics.
    - Will NOT pick the "best" failed attempt for you. best_output is the
      most recent attempt that produced extractable output. If you need
      custom selection, inspect result.events.

    sequence() / retry():
    - Will NOT create workflows or emit workflow events. They are low-level
      composition helpers for step chains. Use @workflow for the full
      TaskResult boundary with events and artifacts.
    """)


if __name__ == "__main__":
    part1_extraction()
    part2_retry_success()
    part3_exhaustion()
    part4_composition()
    part5_boundaries()
