"""Tutorial 04: Agent Stage — using MockAgent in a stage.

Part 1: MockAgent basics — scripted responses, request recording, exhaustion.
Part 2: Agent-backed stage — how the decorator dispatches to an adapter.
Part 3: inject_criteria — how validators become visible to the agent prompt.
Part 4: Inspecting AgentRequest — what the adapter actually receives.
Part 5: MockAgent scripted failures and exception responses.
Part 6: Optional live provider swap (--live flag pattern).
Part 7: What agent stages and MockAgent won't do (by design).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from accentor.core.decorators import stage, workflow
from accentor.dispatch.agents.providers.mock import MockAgent, mock_failure
from accentor.dispatch.agents.base import AgentRequest
from accentor.evaluate.validation import (
    ArrayLength,
    ContainsPhrase,
    JsonRequired,
    NoMarkdownFences,
    TitleMaxWords,
    criteria_description,
)


# ---------------------------------------------------------------------------
# Part 1: MockAgent basics
# ---------------------------------------------------------------------------

def part1_mock_agent() -> None:
    print("=" * 60)
    print("PART 1: MockAgent — scripted responses and recording")
    print("=" * 60)

    # MockAgent consumes scripted responses in order.
    agent = MockAgent(responses=["First response", "Second response"])

    print(f"\n  responses:  {agent.responses}")
    print(f"  exhausted:  {agent.exhausted}")
    print(f"  remaining:  {agent.remaining_responses}")

    # Each .run() consumes the next response.
    request = AgentRequest(prompt="Hello")
    r1 = agent.run(request)
    print(f"\n  run 1: ok={r1.ok}, output={r1.output!r}")
    print(f"  consumed: {agent.consumed_count}, remaining: {agent.remaining_responses}")

    r2 = agent.run(request)
    print(f"  run 2: ok={r2.ok}, output={r2.output!r}")
    print(f"  exhausted: {agent.exhausted}")

    # After exhaustion, runs return a structured failure — not a crash.
    r3 = agent.run(request)
    print(f"\n  run 3 (exhausted): ok={r3.ok}")
    print(f"  diagnostic: {r3.diagnostics[0]['code']}")

    # All requests are recorded for inspection.
    print(f"\n  requests recorded: {len(agent.requests)}")
    print(f"  request[0].prompt: {agent.requests[0].prompt!r}")

    # A single string becomes a one-response agent.
    single = MockAgent(responses="just one")
    print(f"\n  single-response agent: {single.remaining_responses} response")


# ---------------------------------------------------------------------------
# Part 2: Agent-backed stage
# ---------------------------------------------------------------------------

MOCK_RESPONSE = json.dumps({
    "title": "CSV Import Fix",
    "summary": "Blank plan names cause customer impact during onboarding.",
    "risks": ["data loss", "user churn"],
    "next_steps": ["add validation", "improve error message", "notify users"],
})


def part2_agent_stage() -> None:
    print("\n" + "=" * 60)
    print("PART 2: Agent-backed stage — decorator dispatches to adapter")
    print("=" * 60)

    agent = MockAgent(responses=[MOCK_RESPONSE])

    @stage(
        name="summarize_issue",
        agent=agent,
        validators=[
            NoMarkdownFences(),
            JsonRequired(keys=["title", "summary", "risks", "next_steps"]),
            TitleMaxWords(field="title", max_words=10),
            ContainsPhrase(field="summary", phrase="customer impact"),
            ArrayLength(field="risks", exactly=2),
            ArrayLength(field="next_steps", exactly=3),
        ],
        max_attempts=1,
    )
    def summarize_issue(issue_text: str) -> str:
        return f"Summarize this issue:\n{issue_text}"

    @workflow(name="agent_stage_demo")
    def demo() -> dict:
        return summarize_issue("CSV import fails on blank plan names.")

    result = demo()
    print(f"\n  ok:     {result.ok}")
    print(f"  output: {json.dumps(result.output, indent=2)}")

    # The agent received one request.
    print(f"\n  agent ran {agent.run_count} time(s)")
    print(f"  prompt starts with: {agent.requests[0].prompt[:50]!r}...")


# ---------------------------------------------------------------------------
# Part 3: inject_criteria
# ---------------------------------------------------------------------------

def part3_inject_criteria() -> None:
    print("\n" + "=" * 60)
    print("PART 3: inject_criteria — validators visible in the prompt")
    print("=" * 60)

    agent = MockAgent(responses=[MOCK_RESPONSE])

    validators = [
        NoMarkdownFences(),
        JsonRequired(keys=["title", "summary", "risks", "next_steps"]),
        TitleMaxWords(field="title", max_words=10),
        ArrayLength(field="risks", exactly=2),
    ]

    # First: see what criteria_description produces for each validator.
    print(f"\n  Criteria descriptions:")
    for v in validators:
        print(f"    - {criteria_description(v)}")

    @stage(
        name="with_criteria",
        agent=agent,
        validators=validators,
        max_attempts=1,
        inject_criteria=True,
    )
    def with_criteria(issue_text: str, success_criteria: str = "") -> str:
        return f"Summarize:\n{success_criteria}\n\nIssue:\n{issue_text}"

    @workflow(name="criteria_demo")
    def demo() -> dict:
        return with_criteria("CSV import fails.")

    result = demo()
    print(f"\n  ok: {result.ok}")

    # The prompt sent to the agent now contains validator criteria.
    prompt = agent.requests[0].prompt
    print(f"\n  Prompt sent to agent (showing criteria injection):")
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped:
            print(f"    {stripped}")


# ---------------------------------------------------------------------------
# Part 4: Inspecting AgentRequest
# ---------------------------------------------------------------------------

def part4_agent_request() -> None:
    print("\n" + "=" * 60)
    print("PART 4: Inspecting what the adapter receives")
    print("=" * 60)

    agent = MockAgent(responses=[MOCK_RESPONSE])

    @stage(name="inspect_request", agent=agent, max_attempts=1)
    def inspect_request(text: str) -> str:
        return f"Summarize: {text}"

    @workflow(name="request_demo")
    def demo() -> dict:
        return inspect_request("test input")

    demo()

    req = agent.requests[0]
    print(f"\n  AgentRequest fields:")
    print(f"    prompt:           {req.prompt!r}")
    print(f"    timeout_seconds:  {req.timeout_seconds}")
    print(f"    provider_options: {dict(req.provider_options)}")
    print(f"    metadata keys:    {sorted(req.metadata.keys())}")

    # Redacted serialization hides the prompt content.
    redacted = req.redacted()
    print(f"\n  Redacted serialization:")
    print(f"    prompt: {redacted.get('prompt', 'N/A')!r}")


# ---------------------------------------------------------------------------
# Part 5: Scripted failures and exceptions
# ---------------------------------------------------------------------------

def part5_mock_failures() -> None:
    print("\n" + "=" * 60)
    print("PART 5: MockAgent scripted failures and exceptions")
    print("=" * 60)

    # mock_failure() creates a structured failure response.
    agent = MockAgent(responses=[
        mock_failure("Agent timed out after 30s.", code="agent.timeout"),
    ])

    request = AgentRequest(prompt="test")
    result = agent.run(request)
    print(f"\n  Scripted failure:")
    print(f"    ok:          {result.ok}")
    print(f"    output:      {result.output!r}")
    print(f"    diagnostic:  {result.diagnostics[0]['code']}")

    # An exception as a response: simulates adapter crash.
    agent = MockAgent(responses=[ConnectionError("network down")])
    result = agent.run(request)
    print(f"\n  Exception response:")
    print(f"    ok:          {result.ok}")
    print(f"    diagnostic:  {result.diagnostics[0]['code']}")
    print(f"    message:     {result.diagnostics[0]['message']}")

    # Dict response: full control over AgentRunResult fields.
    agent = MockAgent(responses=[{
        "ok": True,
        "output": json.dumps({"custom": "response"}),
    }])
    result = agent.run(request)
    print(f"\n  Dict response:")
    print(f"    ok:     {result.ok}")
    print(f"    output: {result.output!r}")


# ---------------------------------------------------------------------------
# Part 6: Live provider swap
# ---------------------------------------------------------------------------

def part6_live_swap() -> None:
    print("\n" + "=" * 60)
    print("PART 6: Optional live provider swap")
    print("=" * 60)

    def build_agent():
        if "--live" in sys.argv:
            try:
                from accentor.dispatch.agents.providers.codex_cli import CodexCli
                return CodexCli(sandbox="read-only")
            except Exception:
                print("  Live provider unavailable; falling back to MockAgent.")
        return MockAgent(responses=[MOCK_RESPONSE])

    agent = build_agent()
    print(f"\n  Selected adapter: {agent.name}")
    print(f"  Run with --live to use a real provider instead of MockAgent.")


# ---------------------------------------------------------------------------
# Part 7: What agent stages / MockAgent won't do
# ---------------------------------------------------------------------------

def part7_boundaries() -> None:
    print("\n" + "=" * 60)
    print("PART 7: What agent stages and MockAgent won't do")
    print("=" * 60)

    print("""
    Agent stages:
    - Will NOT let the agent decide whether output is acceptable. Validators
      are the judge — the agent is the proposer.
    - Will NOT send the full conversation history. Each attempt gets the
      prompt (with optional criteria and prior failure diagnostics).
    - Will NOT fall back to a different agent on failure. One stage = one
      adapter. Use routing or workflow branching for multi-provider logic.

    MockAgent:
    - Will NOT inspect files, execute code, or modify a workspace. It returns
      scripted text. For repair scenarios that need real file edits, you need
      a file-capable adapter like CodexCli.
    - Will NOT simulate streaming, tool calls, or function calling. It is a
      deterministic test fixture, not an agent emulator.
    - Will NOT infer responses from the prompt. Every response is scripted in
      advance. This is by design: tests should not depend on model behavior.
    """)


if __name__ == "__main__":
    part1_mock_agent()
    part2_agent_stage()
    part3_inject_criteria()
    part4_agent_request()
    part5_mock_failures()
    part6_live_swap()
    part7_boundaries()
