# 03 Validators

**Primitive:** Validators — deterministic checks on stage output.

**What you learn:** How to use built-in validators (`JsonRequired`,
`ArrayLength`, `ForbiddenPattern`, etc.) and write custom validators.

**Run:** `python example.py` (mock-only, no live provider)

## Key Concepts

Validators are pure functions that inspect output and return pass/fail
diagnostics. They run without an agent — you can test them against hand-crafted
strings. A custom validator implements `check(output)` and returns error
messages.

## After This Module

- Next: [04 Agent Stage](../04_agent_stage/)
- See validators in a real use case: [Focused Example 01 — Structured Output](../../focused_examples/01_structured_output/)
- See custom validators: [Focused Example 02 — Citation-Constrained Summary](../../focused_examples/02_citation_constrained_summary/)
