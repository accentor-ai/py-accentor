"""Focused example: deterministic context routing before agent dispatch.

General purpose:
    Show how Accentor can route context inside a task before invoking an agent.
    The router is deterministic Python, while the selected context is used by an
    agentic stage to draft a response.

Toy setting:
    One support ticket could be answered from either a refund-policy brief or a
    CSV-import technical brief. Keyword routing keeps the toy readable while
    still demonstrating selected and omitted context.
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
from accentor.dispatch.routing.base import (
    RouteCandidate,
    RoutingContext,
    RoutingDecision,
)
from accentor.evaluate.validation import (
    ForbiddenPattern,
    JsonFieldEquals,
    JsonRequired,
    NoMarkdownFences,
)


POLICY_CONTEXT = """
Refunds are available for duplicate charges reported within 30 days. Ask for
the invoice id if it is missing. Do not promise a refund before verification.
"""

TECHNICAL_CONTEXT = """
CSV imports accept UTF-8 files with headers. Blank optional fields are allowed,
but required columns must be present: account_id, plan_name, and start_date.
"""

TICKET = """
The customer says their CSV import fails after upload. The message only says
"something went wrong." They attached a file with blank plan_name values.
"""


def ticket_router(context: RoutingContext) -> RoutingDecision:
    # The router sees structured stage input and returns an explicit decision.
    # In a real system this could use tags, customer tier, product area, or a
    # deterministic classifier with a confidence threshold.
    ticket = context.input["ticket"].lower()
    if "csv" in ticket or "import" in ticket:
        return RoutingDecision(
            selected="technical",
            rationale="Ticket is about CSV import behavior.",
        )

    return RoutingDecision(
        selected="policy",
        rationale="Ticket appears to be about account policy.",
    )


# The route candidates are named pieces of context. Accentor records which one
# was selected, then injects only that context into the prompt as routed_context.
@stage(
    name="draft_support_reply",
    router=ticket_router,
    route_candidates=[
        RouteCandidate(name="policy", context=POLICY_CONTEXT),
        RouteCandidate(name="technical", context=TECHNICAL_CONTEXT),
    ],
    agent=CodexCli(sandbox="read-only"),
    validators=[
        NoMarkdownFences(),
        JsonRequired(keys=["reply", "next_question", "context_used"]),
        # The output must make the selected route observable to reviewers and
        # downstream code.
        JsonFieldEquals(field="context_used", value="technical"),
        # This protects the technical branch from drifting into policy promises.
        ForbiddenPattern(r"\brefund approved\b", "unverified refund promise"),
    ],
    max_attempts=2,
    inject_criteria=True,
)
def draft_support_reply(
    ticket: str,
    routed_context: str,
    success_criteria: str = "",
) -> str:
    return f"""
    Draft a concise support reply.

    {success_criteria}

    Ticket:
    {ticket}

    Selected context:
    {routed_context}
    """


@workflow(name="support_reply_with_intra_task_routing")
def support_reply_with_intra_task_routing() -> dict:
    # The workflow caller does not choose the context directly; that decision is
    # part of the recorded stage boundary.
    return draft_support_reply(TICKET)


def _separator(label: str = "") -> None:
    if label:
        print(f"\n{'─' * 20} {label} {'─' * 20}")
    else:
        print(f"{'─' * 60}")


def _print_result(result) -> None:
    _separator("WORKFLOW: support_reply_with_intra_task_routing")

    print(f"Status   : {'PASS' if result.ok else 'FAIL'}")
    print(f"Attempts : {result.attempt_count}")

    routing_events = [e for e in result.events if e.routing]
    if routing_events:
        _separator("ROUTING")
        for e in routing_events:
            r = e.routing
            print(f"  Selected : {r.get('selected', '?')}")
            print(f"  Rationale: {r.get('rationale', '?')}")
            omitted = r.get("omitted")
            if omitted:
                print(f"  Omitted  : {', '.join(omitted)}")

    validators = draft_support_reply.__accentor_stage_config__.validators
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
    result = support_reply_with_intra_task_routing()
    _print_result(result)
