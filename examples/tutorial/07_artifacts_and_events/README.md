# 07 Artifacts And Events

**Primitive:** Artifact root, event streams, and inspection.

**What you learn:** How to configure `artifact_root`, what files a workflow
writes (`events.jsonl`, prompt snapshots, raw responses, validation reports,
`task_result.json`), and how to inspect them.

**Run:** `python example.py` (mock-only, no live provider)

## Key Concepts

Every workflow run can produce a structured artifact directory. Events are
recorded as they happen. After the run, a reviewer can reconstruct the full
decision chain: what the agent saw, what it returned, what validators said,
and what was accepted or rejected.

## After This Module

- Next: [08 Scoped Repair](../08_scoped_repair/)
- See artifacts in a real use case: [Focused Example 05 — Exception Repair](../../focused_examples/05_exception_repair/)
