# Tutorial

Learn Accentor primitives step by step. Each module teaches one concept with
mock agents, so you can run everything locally without a live provider.

## Prerequisites

```bash
pip install -e .
```

## Modules

Work through these in order. Each module builds on the previous ones.

| # | Module | What You Learn |
|---|--------|----------------|
| 1 | [01_task_result/](01_task_result/) | `TaskResult` fields: `ok`, `output`, `best_output`, `diagnostics`, `attempt_count` |
| 2 | [02_stage_and_workflow/](02_stage_and_workflow/) | Ordinary Python functions as stages, composed in a workflow |
| 3 | [03_validators/](03_validators/) | Deterministic validation without agents; custom validators |
| 4 | [04_agent_stage/](04_agent_stage/) | `MockAgent`, `AgentRequest`, `inject_criteria`, optional live swap |
| 5 | [05_extraction_and_retry/](05_extraction_and_retry/) | Bad output, validation failure, retry loop, diagnostics |
| 6 | [06_routing/](06_routing/) | Deterministic route selection and context exclusion |
| 7 | [07_artifacts_and_events/](07_artifacts_and_events/) | `artifact_root`, `events.jsonl`, prompt snapshots, validation reports |
| 8 | [08_scoped_repair/](08_scoped_repair/) | Exception-triggered repair with scoped file access and rerun validation |

## After The Tutorial

Once you understand the primitives, explore:

- [Focused examples](../focused_examples/) — capability recipes that apply
  these primitives in realistic use cases.

## Testing

All tutorial examples run with mocks by default and are safe for pytest:

```bash
python3 -m pytest tests/ -q
```

Live provider behavior is opt-in with `--live` where supported.
