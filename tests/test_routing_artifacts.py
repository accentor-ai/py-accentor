from __future__ import annotations

import json
from pathlib import Path

from accentor.core.composition.routing import routing_input_for_call
from accentor.core.decorators import stage, workflow
from accentor.dispatch.agents.providers.mock import MockAgent
from accentor.dispatch.routing.base import RouteCandidate, RoutingContext, RoutingDecision
from accentor.evaluate.validation import JsonFieldEquals, JsonRequired, NoMarkdownFences


POLICY_CONTEXT = """
Refunds are available for duplicate charges reported within 30 days. Ask for
the invoice id if it is missing. Do not promise a refund before verification.
"""

TECHNICAL_CONTEXT = """
CSV imports accept UTF-8 files with headers. Blank optional fields are allowed,
but required columns must be present: account_id, plan_name, and start_date.
"""

TICKETS = [
    {
        "ticket_id": "T-technical",
        "body": "The customer says their CSV import fails after upload.",
        "expected_route": "technical",
    },
    {
        "ticket_id": "T-policy",
        "body": "The customer was charged twice and asks about a refund.",
        "expected_route": "policy",
    },
]


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _ticket_router(context: RoutingContext) -> RoutingDecision:
    ticket = context.input["ticket"].lower()
    if "csv" in ticket or "import" in ticket:
        return RoutingDecision(selected="technical", rationale="Ticket is about CSV import behavior.")
    return RoutingDecision(selected="policy", rationale="Ticket appears to be about account policy.")


def test_routing_input_excludes_framework_injected_parameters() -> None:
    def prompt_source(
        ticket: str,
        routed_context: str,
        success_criteria: str = "",
        ctx: object | None = None,
    ) -> str:
        return ticket

    assert routing_input_for_call(
        prompt_source,
        ("ticket body",),
        {
            "routed_context": "selected context",
            "success_criteria": "criteria",
            "ctx": object(),
        },
    ) == {"ticket": "ticket body"}


def test_routed_workflows_write_per_invocation_jsonl_for_both_p0_04_branches(tmp_path: Path) -> None:
    agent = MockAgent(
        responses=[
            '{"reply": "Check the CSV columns.", "next_question": "Can you confirm headers?", "context_used": "technical"}',
            '{"reply": "Billing should review this.", "next_question": "Can you share the invoice id?", "context_used": "policy"}',
        ]
    )
    seen_contexts: list[RoutingContext] = []

    def recording_router(context: RoutingContext) -> RoutingDecision:
        seen_contexts.append(context)
        return _ticket_router(context)

    @stage(
        name="draft_support_reply",
        router=recording_router,
        route_candidates=[
            RouteCandidate(name="policy", context=POLICY_CONTEXT),
            RouteCandidate(name="technical", context=TECHNICAL_CONTEXT),
        ],
        agent=agent,
        validators=[
            NoMarkdownFences(),
            JsonRequired(keys=["reply", "next_question", "context_used"]),
        ],
        inject_criteria=True,
    )
    def draft_support_reply(
        ticket: str,
        routed_context: str,
        success_criteria: str = "",
    ) -> str:
        return f"""
        Draft a concise support reply. Return JSON only.

        {success_criteria}

        Ticket:
        {ticket}

        Selected context:
        {routed_context}
        """

    for index, ticket in enumerate(TICKETS):
        ticket_root = tmp_path / ticket["ticket_id"]

        @workflow(name=f"routing_artifacts_{ticket['ticket_id']}")
        def one_ticket_workflow() -> dict:
            return draft_support_reply(ticket=ticket["body"])

        result = one_ticket_workflow(artifact_root=ticket_root)

        assert result.ok is True
        assert result.output["context_used"] == ticket["expected_route"]

        records = _read_jsonl(ticket_root / "routing_decisions.jsonl")
        assert len(records) == 1
        record = records[0]
        assert record["selected"] == ticket["expected_route"]
        assert record["selected_candidate"] == ticket["expected_route"]
        assert record["stage"] == "draft_support_reply"
        assert record["run_id"]
        assert record["metadata"]["input_keys"] == ["ticket"]
        assert set(record["omitted"]) == {"policy", "technical"} - {ticket["expected_route"]}
        assert record["rationale"]

        artifact_text = (ticket_root / "routing_decisions.jsonl").read_text(encoding="utf-8")
        assert POLICY_CONTEXT.strip() not in artifact_text
        assert TECHNICAL_CONTEXT.strip() not in artifact_text

        prompt = agent.requests[index].prompt or ""
        selected_context = TECHNICAL_CONTEXT if ticket["expected_route"] == "technical" else POLICY_CONTEXT
        omitted_context = POLICY_CONTEXT if ticket["expected_route"] == "technical" else TECHNICAL_CONTEXT
        assert selected_context.strip() in prompt
        assert omitted_context.strip() not in prompt

    assert [context.input for context in seen_contexts] == [{"ticket": ticket["body"]} for ticket in TICKETS]


def test_unknown_route_fails_before_agent_dispatch_and_records_decision(tmp_path: Path) -> None:
    agent = MockAgent(responses=['{"ok": true}'])

    def missing_router(context: RoutingContext) -> RoutingDecision:
        return RoutingDecision(selected="missing", rationale="No configured route matches.")

    @stage(
        name="bad_route",
        router=missing_router,
        route_candidates=[RouteCandidate(name="known", context="Known context.")],
        agent=agent,
        validators=[JsonRequired(keys=["ok"])],
    )
    def bad_route(ticket: str, routed_context: str) -> str:
        return f"{ticket}\n{routed_context}"

    @workflow(name="bad_route_workflow")
    def bad_route_workflow() -> dict:
        return bad_route(ticket="anything")

    result = bad_route_workflow(artifact_root=tmp_path)

    assert result.ok is False
    assert agent.run_count == 0
    assert any(diagnostic.code == "routing.no_match" for diagnostic in result.diagnostics)

    records = _read_jsonl(tmp_path / "routing_decisions.jsonl")
    assert records[0]["selected"] == "missing"
    assert records[0]["selected_candidate"] is None
    assert records[0]["omitted"] == ["known"]
    assert [diagnostic["code"] for diagnostic in records[0]["diagnostics"]] == ["routing.no_match"]


def test_route_output_mismatch_uses_existing_validation_pipeline(tmp_path: Path) -> None:
    agent = MockAgent(
        responses=[
            '{"reply": "Policy answer.", "next_question": "Invoice id?", "context_used": "policy"}'
        ]
    )

    @stage(
        name="route_mismatch",
        router=lambda context: RoutingDecision(selected="technical", rationale="Force technical route."),
        route_candidates=[
            RouteCandidate(name="policy", context=POLICY_CONTEXT),
            RouteCandidate(name="technical", context=TECHNICAL_CONTEXT),
        ],
        agent=agent,
        validators=[
            JsonRequired(keys=["reply", "next_question", "context_used"]),
            JsonFieldEquals(field="context_used", value="technical"),
        ],
    )
    def route_mismatch(ticket: str, routed_context: str) -> str:
        return f"{ticket}\n{routed_context}"

    @workflow(name="route_mismatch_workflow")
    def route_mismatch_workflow() -> dict:
        return route_mismatch(ticket="csv import issue")

    result = route_mismatch_workflow(artifact_root=tmp_path)

    assert result.ok is False
    assert agent.run_count == 1
    assert any(diagnostic.code == "validation.json_field_mismatch" for diagnostic in result.diagnostics)
    assert _read_jsonl(tmp_path / "routing_decisions.jsonl")[0]["selected"] == "technical"
