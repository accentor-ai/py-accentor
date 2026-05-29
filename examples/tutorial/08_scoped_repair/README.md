# 08 Scoped Repair

**Primitive:** Exception-triggered agentic repair with scoped file access.

**What you learn:** How `on_error` activates repair, how `readable` and
`editable` constrain the repair agent, how the pipeline reruns and validates.

**Run:** `python example.py` (mock-only, no live provider)

## Key Concepts

When a conventional stage raises a declared exception, an agent can attempt a
scoped repair. The agent sees only declared files and may edit only declared
files. The pipeline reruns, and exact validators decide whether the repair is
accepted.

## After This Module

You have completed the tutorial. Next steps:

- [Focused examples](../../focused_examples/) — capability recipes applying
  these primitives in realistic use cases.
- Especially: [Focused Example 05 — Exception Repair](../../focused_examples/05_exception_repair/).
