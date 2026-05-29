# Intra-Task Routing

**What this demonstrates:** Deterministic context selection before agent
execution — the agent sees only the routed brief, not everything.
**Run:** `python example.py` (uses `CodexCli` — live provider)
**Expected output shape:**
```json
{"reply": "...", "next_question": "...", "context_used": "technical"}
```
**What to inspect afterward:** `routing_decision.json`, `selected_context.txt`,
`validation_report_attempt_0.json`, `task_result.json`
**Tutorial prerequisite:** [06 Routing](../../tutorial/06_routing/)

---

## Purpose And Boundary

Before the agent sees the ticket, deterministic routing chooses the relevant
context. The agent receives the selected brief, not every possible policy or
technical source. This keeps prompt construction auditable and prevents
irrelevant context from steering the answer.

In `example.py`, a CSV-import ticket routes to `technical`. The accepted output
must then say `context_used` is `technical`, making the route visible in the JSON
returned to the caller.

## Toy Flow

1. `TICKET` describes a CSV import failure.
2. `ticket_router(...)` inspects structured stage input.
3. The router returns `RoutingDecision(selected="technical", ...)`.
4. Accentor injects the selected candidate context as `routed_context`.
5. The agent drafts a support reply from the selected context.
6. Validators reject route drift and policy promises.

## Parameters To Try

`RouteCandidate(name="policy", context=POLICY_CONTEXT)` and
`RouteCandidate(name="technical", context=TECHNICAL_CONTEXT)` are the candidate
briefs. Adding a billing, security, or product-announcement candidate would
expand the router's decision space.

`ticket_router(...)` currently uses keywords. A production router might use
ticket metadata, a deterministic rules table, a classifier with a confidence
threshold, or a fallback route for ambiguous tickets.

`JsonFieldEquals(field="context_used", value="technical")` is hard-coded because
the toy ticket should route to `technical`. A reusable test could compare the
agent output to the recorded routing decision instead.

The `ForbiddenPattern(r"\brefund approved\b", ...)` check protects this branch
from policy drift. A policy-route version would use different validators, such
as "must ask for invoice id if missing."

## Internal Data Shapes

The router receives a context object conceptually shaped like this:

```json
{
  "stage": "draft_support_reply",
  "input": {
    "ticket": "The customer says their CSV import fails after upload..."
  },
  "candidate_names": ["policy", "technical"]
}
```

The routing decision is a first-class record:

```json
{
  "selected": "technical",
  "rationale": "Ticket is about CSV import behavior.",
  "candidates": ["policy", "technical"],
  "omitted": ["policy"]
}
```

An accepted output should keep the selected route observable:

```json
{
  "reply": "Sorry the CSV import failed. Blank plan_name values can cause import issues when that column is required.",
  "next_question": "Can you confirm whether every row includes account_id, plan_name, and start_date?",
  "context_used": "technical"
}
```

## Behavior In Other Settings

For customer support, routing can keep policy, troubleshooting, and billing
briefs separate. For developer tools, it can choose the relevant package docs
before asking an agent to explain an error. For internal operations, it can send
the same request to different validators depending on region, product, or risk.

If a ticket matches multiple routes, the router should return an explicit
fallback decision or ambiguity diagnostic rather than silently concatenating all
context. If the chosen context is large, the selected material should itself be
recorded as an artifact so reviewers can reconstruct the prompt.

## Expected Artifacts

```text
routing_decision.json
selected_context.txt
omitted_contexts.json
prompt_attempt_0.md
validation_report_attempt_0.json
task_result.json
```

## Failure Scenarios

If the agent says `context_used` is `policy`, `JsonFieldEquals` rejects the
reply.

If the agent promises `refund approved`, `ForbiddenPattern` rejects the reply.

If a second ticket mentions duplicate charges instead of CSV imports, the same
router should select `policy`. That branch belongs in a companion test or README
example rather than making the first script harder to read.

## Bigger Picture

Routing is how a workflow keeps context selection inspectable. Without it, agent
prompts tend to accumulate every relevant-looking source, which makes later
debugging and security review much harder.

## Ask Your Agent

This example is reference material for a coding agent to draft your own
routing workflow. Point the agent here and describe your use case:

> See `examples/focused_examples/04_intra_task_routing/example.py` as
> reference. Write me an Accentor file for our support console: incoming
> tickets should be routed to one of three context bundles — billing, product,
> or security — based on keywords in the subject and body. The agent drafts a
> reply using only the selected context. Validate that the reply declares which
> context was used, and reject any reply that promises a refund on the
> technical or security routes.

Other prompts that use this pattern:

- "Draft an Accentor file for our developer docs assistant: route user
  questions to the relevant package documentation section before the agent
  answers, so it never sees unrelated API surfaces."
- "Generate an Accentor file for an operations triage system: route cloud
  infrastructure alerts to region-specific runbooks before asking an agent
  to draft an incident response plan."

## API Pressure

This example forces stable answers for:

- how `routed_context` is injected into the stage function
- whether `RoutingDecision` includes selected context, metadata, or only labels
- how selected and omitted context are recorded as artifacts
- which routing events belong in the workflow timeline
