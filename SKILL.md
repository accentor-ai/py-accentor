---
name: accentor
description: Use when authoring, modifying, reviewing, or testing Accentor Python workflows that combine deterministic code with agent-backed stages, validators, routing, artifacts, scoped repair, provider adapters, MockAgent, or CodexCli.
---

# Accentor

Hybrid agentic-conventional workflow library. Deterministic Python owns
preparation, routing, validation, artifacts, and repair boundaries; agents
contribute only where judgment is needed. Every agent output crosses a
deterministic gate before downstream code trusts it.

## Orientation — read these first

- Package source: `accentor/` (especially `core/`, `evaluate/validation/`, `dispatch/`)
- Tutorial examples (progressive): `examples/tutorial/01_task_result/` … `08_scoped_repair/`
- Focused recipes: `examples/focused_examples/01_structured_output/` … `06_adapter_contract/`
- Docs: `docs/getting_started.rst`, `docs/walkthrough/`

When working on a pattern, read the closest existing example and preserve its
boundary shape. The source and examples are the authority — don't guess APIs.


## Key rules

- `@workflow` wraps user-facing flows; returns `TaskResult`. Use `return_result=False` only when caller wants exceptions/raw output.
- `@stage` for deterministic steps, prompt builders, routing, and repair boundaries.
- Agent-backed stages: function builds the prompt; decorator gets `agent`, `validators`, `max_attempts`, usually `inject_criteria=True`.
- Validators are the acceptance contract. Prefer built-ins from `accentor.evaluate.validation` — read that module for the full list.
- Custom validators: subclass `Validator`, return `list[str]` (empty = pass).
- `MockAgent` for tests and deterministic examples. `CodexCli` only for live runs.
- `CodexCli(sandbox="read-only")` for drafting; `"workspace-write"` only when the agent must edit files.
- Branch on `result.ok`. Surface `result.diagnostics` on failure; keep `result.best_output` for debugging.
- Redact sensitive values before dispatch. Mirror redaction rules with `ForbiddenPattern` validators.
- Only `codex_cli` and `mock` provider adapters are available on this branch.
