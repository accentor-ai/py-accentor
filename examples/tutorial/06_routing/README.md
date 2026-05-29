# 06 Routing

**Primitive:** Deterministic route selection and context exclusion.

**What you learn:** How to define route candidates, write a router function,
and ensure the agent sees only selected context.

**Run:** `python example.py` (mock-only, no live provider)

## Key Concepts

A router inspects stage input and selects one context bundle from named
candidates. The agent receives only the selected context — omitted candidates
are recorded but never injected. This keeps prompt construction auditable and
prevents irrelevant context from steering the answer.

## After This Module

- Next: [07 Artifacts and Events](../07_artifacts_and_events/)
- See routing in a real use case: [Focused Example 04 — Intra-Task Routing](../../focused_examples/04_intra_task_routing/)
