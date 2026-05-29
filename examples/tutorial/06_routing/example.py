"""Tutorial 06: Routing — deterministic context selection.

Part 1: RouteCandidate and RoutingDecision — the data shapes.
Part 2: Router function — inspecting input, returning decisions.
Part 3: Routing in a stage — routed_context injection, omitted candidates.
Part 4: Multiple tickets — showing different routes are selected.
Part 5: Ambiguous routing — confidence, diagnostics, fallback patterns.
Part 6: What routing won't do (by design).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from accentor.core.decorators import stage, workflow
from accentor.dispatch.agents.providers.mock import MockAgent
from accentor.dispatch.routing.base import (
    RouteCandidate,
    RoutingContext,
    RoutingDecision,
    RoutingDiagnostic,
)
from accentor.evaluate.validation import (
    JsonFieldEquals,
    JsonRequired,
    NoMarkdownFences,
)


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------

POLICY_CONTEXT = """\
Refunds are available for duplicate charges within 30 days. Ask for the
invoice ID if missing. Do not promise a refund before verification."""

TECHNICAL_CONTEXT = """\
CSV imports accept UTF-8 files. Required columns: account_id, plan_name,
start_date. Blank optional fields are allowed."""

BILLING_CONTEXT = """\
Billing issues should be escalated to finance. Common causes: expired card,
currency mismatch, duplicate subscription."""


# ---------------------------------------------------------------------------
# Part 1: RouteCandidate and RoutingDecision
# ---------------------------------------------------------------------------

def part1_data_shapes() -> None:
    print("=" * 60)
    print("PART 1: RouteCandidate and RoutingDecision — data shapes")
    print("=" * 60)

    # RouteCandidate: named piece of context that a router can select.
    tech = RouteCandidate(name="technical", context=TECHNICAL_CONTEXT)
    policy = RouteCandidate(name="policy", context=POLICY_CONTEXT)
    billing = RouteCandidate(
        name="billing",
        context=BILLING_CONTEXT,
        metadata={"escalation_required": True},
    )

    print(f"\n  Candidates:")
    for c in [tech, policy, billing]:
        ctx_preview = c.context[:40].replace("\n", " ")
        print(f"    {c.name}: {ctx_preview}...")
        if c.metadata:
            print(f"      metadata: {dict(c.metadata)}")

    # RoutingDecision: what the router returns.
    decision = RoutingDecision(
        selected="technical",
        rationale="Ticket mentions CSV import.",
        confidence=0.9,
        candidates=("technical", "policy", "billing"),
        omitted=("policy", "billing"),
    )

    print(f"\n  Decision:")
    print(f"    selected:   {decision.selected}")
    print(f"    rationale:  {decision.rationale}")
    print(f"    confidence: {decision.confidence}")
    print(f"    candidates: {decision.candidates}")
    print(f"    omitted:    {decision.omitted}")

    # Serialization for artifacts.
    print(f"\n  to_dict() keys: {sorted(decision.to_dict().keys())}")


# ---------------------------------------------------------------------------
# Part 2: Router function
# ---------------------------------------------------------------------------

def ticket_router(context: RoutingContext) -> RoutingDecision:
    """Keyword router — production routers can be classifiers, rule engines, etc."""
    ticket = context.input.get("ticket", "").lower()
    candidates = context.candidate_names

    if "csv" in ticket or "import" in ticket or "upload" in ticket:
        selected = "technical"
        rationale = "Ticket mentions CSV/import keywords."
        confidence = 0.9
    elif "refund" in ticket or "charge" in ticket or "invoice" in ticket:
        selected = "policy"
        rationale = "Ticket mentions refund/charge keywords."
        confidence = 0.85
    elif "billing" in ticket or "payment" in ticket or "card" in ticket:
        selected = "billing"
        rationale = "Ticket mentions billing/payment keywords."
        confidence = 0.8
    else:
        selected = "policy"
        rationale = "No strong keyword match; defaulting to policy."
        confidence = 0.3

    return RoutingDecision(
        selected=selected,
        rationale=rationale,
        confidence=confidence,
        candidates=candidates,
        omitted=tuple(c for c in candidates if c != selected),
    )


def part2_router_function() -> None:
    print("\n" + "=" * 60)
    print("PART 2: Router function — inspect input, return decision")
    print("=" * 60)

    # The router receives RoutingContext with stage name, input, candidate names.
    ctx = RoutingContext(
        stage="draft_reply",
        input={"ticket": "My CSV upload fails with blank plan names."},
        candidate_names=("technical", "policy", "billing"),
    )

    decision = ticket_router(ctx)
    print(f"\n  Input: {dict(ctx.input)['ticket']}")
    print(f"  Selected: {decision.selected} (confidence={decision.confidence})")
    print(f"  Rationale: {decision.rationale}")
    print(f"  Omitted: {decision.omitted}")


# ---------------------------------------------------------------------------
# Part 3: Routing in a stage
# ---------------------------------------------------------------------------

def part3_routed_stage() -> None:
    print("\n" + "=" * 60)
    print("PART 3: Routing in a stage — context injection")
    print("=" * 60)

    mock_reply = json.dumps({
        "reply": "Check that required columns are present in your CSV file.",
        "context_used": "technical",
    })

    agent = MockAgent(responses=[mock_reply])

    @stage(
        name="draft_reply",
        router=ticket_router,
        route_candidates=[
            RouteCandidate(name="policy", context=POLICY_CONTEXT),
            RouteCandidate(name="technical", context=TECHNICAL_CONTEXT),
            RouteCandidate(name="billing", context=BILLING_CONTEXT),
        ],
        agent=agent,
        validators=[
            NoMarkdownFences(),
            JsonRequired(keys=["reply", "context_used"]),
            JsonFieldEquals(field="context_used", value="technical"),
        ],
        max_attempts=1,
        inject_criteria=True,
    )
    def draft_reply(ticket: str, routed_context: str, success_criteria: str = "") -> str:
        return f"Draft a reply.\n{success_criteria}\nTicket: {ticket}\nContext: {routed_context}"

    @workflow(name="routed_demo")
    def demo() -> dict:
        return draft_reply(ticket="My CSV upload fails.")

    result = demo()
    print(f"\n  ok:     {result.ok}")
    print(f"  output: {json.dumps(result.output, indent=2)}")

    # The prompt received by the agent contains ONLY the selected context.
    prompt = agent.requests[0].prompt
    has_technical = "CSV imports" in prompt
    has_policy = "Refunds are" in prompt
    has_billing = "Billing issues" in prompt
    print(f"\n  Prompt contains technical context: {has_technical}")
    print(f"  Prompt contains policy context:    {has_policy}")
    print(f"  Prompt contains billing context:   {has_billing}")

    # Routing decision is recorded as an event.
    for event in result.events:
        if event.event_type == "routing.decided" and event.routing:
            print(f"\n  Routing event:")
            print(f"    selected:  {event.routing.get('selected')}")
            print(f"    rationale: {event.routing.get('rationale')}")


# ---------------------------------------------------------------------------
# Part 4: Multiple tickets — different routes
# ---------------------------------------------------------------------------

def part4_multiple_tickets() -> None:
    print("\n" + "=" * 60)
    print("PART 4: Multiple tickets — different routes selected")
    print("=" * 60)

    tickets = [
        ("My CSV upload fails.", "technical"),
        ("I was charged twice for my subscription.", "policy"),
        ("My payment card was declined.", "billing"),
        ("How do I use your product?", "policy"),
    ]

    for ticket_text, expected in tickets:
        ctx = RoutingContext(
            stage="draft_reply",
            input={"ticket": ticket_text},
            candidate_names=("technical", "policy", "billing"),
        )
        decision = ticket_router(ctx)
        match = "OK" if decision.selected == expected else "MISMATCH"
        print(f"\n  [{match}] '{ticket_text}'")
        print(f"    -> {decision.selected} (confidence={decision.confidence}, "
              f"rationale={decision.rationale})")


# ---------------------------------------------------------------------------
# Part 5: Ambiguous routing
# ---------------------------------------------------------------------------

def part5_ambiguous() -> None:
    print("\n" + "=" * 60)
    print("PART 5: Ambiguous routing — low confidence, diagnostics")
    print("=" * 60)

    # The fallback case: no strong keyword match.
    ctx = RoutingContext(
        stage="draft_reply",
        input={"ticket": "I have a general question about my account."},
        candidate_names=("technical", "policy", "billing"),
    )

    decision = ticket_router(ctx)
    print(f"\n  Ambiguous ticket: '{dict(ctx.input)['ticket']}'")
    print(f"  Selected:   {decision.selected}")
    print(f"  Confidence: {decision.confidence}")
    print(f"  Rationale:  {decision.rationale}")

    # A router can also emit diagnostics when uncertain.
    def cautious_router(context: RoutingContext) -> RoutingDecision:
        ticket = context.input.get("ticket", "").lower()
        matches = []
        if "csv" in ticket or "import" in ticket:
            matches.append("technical")
        if "refund" in ticket or "charge" in ticket:
            matches.append("policy")

        if len(matches) > 1:
            return RoutingDecision(
                selected=matches[0],
                rationale="Multiple topics detected; using first match.",
                confidence=0.4,
                diagnostics=(
                    RoutingDiagnostic(
                        code="routing.ambiguous",
                        message=f"Ticket matched {len(matches)} routes: {matches}",
                        severity="warning",
                    ),
                ),
            )
        if not matches:
            return RoutingDecision(
                selected="policy",
                rationale="No match; defaulting to policy.",
                confidence=0.2,
            )
        return RoutingDecision(selected=matches[0], rationale="Single match.", confidence=0.9)

    # Ambiguous ticket that matches both technical and policy.
    ctx = RoutingContext(
        stage="test",
        input={"ticket": "My CSV import was charged twice."},
        candidate_names=("technical", "policy"),
    )
    decision = cautious_router(ctx)
    print(f"\n  Multi-match ticket: 'My CSV import was charged twice.'")
    print(f"  Selected:   {decision.selected}")
    print(f"  Confidence: {decision.confidence}")
    if decision.diagnostics:
        for d in decision.diagnostics:
            print(f"  Diagnostic: [{d.severity}] {d.code}: {d.message}")


# ---------------------------------------------------------------------------
# Part 6: What routing won't do
# ---------------------------------------------------------------------------

def part6_boundaries() -> None:
    print("\n" + "=" * 60)
    print("PART 6: What routing won't do (by design)")
    print("=" * 60)

    print("""
    Routing:
    - Will NOT use an LLM to classify tickets. The router is a Python
      callable — keywords, rule engines, or classifiers you control.
    - Will NOT select multiple routes. One decision = one selected candidate.
      If you need multi-context, build a composite context in your router.
    - Will NOT inject omitted context. Only the selected candidate's context
      reaches routed_context. Omitted candidates are recorded in the event
      but never sent to the agent. This is the core auditability guarantee.
    - Will NOT fall back to a different route on validation failure. If the
      agent's response fails validation, retry uses the same route. Changing
      route on failure would require a new stage with different routing logic.
    - Will NOT cache routing decisions across stages. Each stage call invokes
      the router fresh. Stateful routing requires explicit state in your router.
    """)


if __name__ == "__main__":
    part1_data_shapes()
    part2_router_function()
    part3_routed_stage()
    part4_multiple_tickets()
    part5_ambiguous()
    part6_boundaries()
