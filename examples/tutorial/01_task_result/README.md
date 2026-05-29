# 01 Task Result

**Primitive:** `TaskResult` — the standard return type from every Accentor
workflow.

**What you learn:** How to read `ok`, `output`, `best_output`, `diagnostics`,
and `attempt_count`. How to branch on `result.ok`.

**Run:** `python example.py` (mock-only, no live provider)

## Key Concepts

A `TaskResult` tells you whether the workflow accepted an output and why. Every
downstream consumer — CLI scripts, web endpoints, review dashboards — branches
on `result.ok` rather than inspecting raw agent text.

## After This Module

- Next: [02 Stage and Workflow](../02_stage_and_workflow/)
- See this in a real use case: [Focused Example 01 — Structured Output](../../focused_examples/01_structured_output/)
