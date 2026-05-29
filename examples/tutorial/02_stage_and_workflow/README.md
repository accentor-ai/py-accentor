# 02 Stage And Workflow

**Primitive:** `@stage` and `@workflow` decorators.

**What you learn:** How ordinary Python functions become stages and how stages
compose into workflows.

**Run:** `python example.py` (mock-only, no live provider)

## Key Concepts

A stage is a decorated Python function that Accentor tracks. A workflow
composes stages into a sequence with shared artifact and event context. Stages
can be purely conventional (no agent) or agentic.

## After This Module

- Next: [03 Validators](../03_validators/)
- See stages in a real use case: [Focused Example 05 — Exception Repair](../../focused_examples/05_exception_repair/)
