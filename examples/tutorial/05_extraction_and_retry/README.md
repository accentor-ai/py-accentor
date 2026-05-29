# 05 Extraction And Retry

**Primitive:** JSON extraction, validation failure, and retry loop.

**What you learn:** What happens when agent output fails validation — how
diagnostics form, how remediation prompts work, how `attempt_count` and
`best_output` track progress.

**Run:** `python example.py` (mock-only, no live provider)

## Key Concepts

When a validator rejects output, Accentor can retry with a remediation prompt
that includes the specific failure diagnostics. The retry loop is bounded by
`max_attempts`. If all attempts fail, `best_output` preserves the closest
result.

## After This Module

- Next: [06 Routing](../06_routing/)
- See retry in a real use case: [Focused Example 01 — Structured Output](../../focused_examples/01_structured_output/)
