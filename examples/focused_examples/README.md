# Focused Examples — Capability Recipes

These are **capability recipes**, not a tutorial. Each one demonstrates a
distinct Accentor capability in a small, realistic use case. They assume you
already understand stages, validators, tasks, artifacts, and dispatch.

**New to Accentor?** Start with the [tutorial](../tutorial/) to learn primitives
step by step, then come back here to see them applied.

## Who Writes These Files

Accentor `.py` files are designed to be **authored by coding agents** for
specific user workflows. The examples here are reference material — they show
the patterns, imports, and boundary conventions that an agent needs to produce a
working file for your use case.

The expected workflow is:

1. Point your coding agent at a focused example and your own context.
2. Describe the hybrid process you need.
3. The agent drafts an Accentor `.py` file tailored to your inputs, validators,
   routing, and artifact expectations.
4. You review, adjust, and run.

If the agent has access to `SKILL.md` and to these example files, it should be
able to produce a use-case-specific Accentor file from a short natural-language
prompt. The examples below each include a sample prompt to illustrate how this
works in practice.

## Structure

Each example is deliberately split into two parts:

- `example.py`: the smallest readable usage sketch for the package API.
- `README.md`: the boundary narrative, expected artifacts, failure scenarios,
  package-design pressure, and an example agent prompt for generating a
  real-world variant.

The Python files should stay runnable-looking and compact. The READMEs should do
the heavier explanatory work.

## Current Examples

Examples are ordered from simplest to most advanced but can be read
independently. Each README has a quick-start header with run instructions
and expected output shape.

| # | Directory | Capability | Live Provider? |
|---|-----------|------------|:--------------:|
| 1 | [01_structured_output/](01_structured_output/) | Deterministic validation gates on agent output | Yes (`CodexCli`) |
| 2 | [02_citation_constrained_summary/](02_citation_constrained_summary/) | Source-derived constraints fencing agentic prose | Yes (`CodexCli`) |
| 3 | [03_pii_filtered_draft/](03_pii_filtered_draft/) | Privacy boundary: redact before dispatch, validate after | Yes (`CodexCli`) |
| 4 | [04_intra_task_routing/](04_intra_task_routing/) | Deterministic context routing before agent execution | Yes (`CodexCli`) |
| 5 | [05_exception_repair/](05_exception_repair/) | Scoped agentic repair after declared conventional failure | Yes (`CodexCli`) |
| 6 | [06_adapter_contract/](06_adapter_contract/) | Provider adapter conformance testing *(Developer-focused)* | Mock default, `--live` opt-in |

## File Contract

Every focused example should preserve this shape:

```text
examples/focused_examples/<nn_example_name>/
  example.py
  README.md
  inputs/ or data/  # only when the example needs fixtures
```

`example.py` should be digestible in one sitting. Prefer obvious Python,
canonical imports, and comments that orient the reader to why the stage,
validator, route, permission scope, or result branch exists.

`README.md` should carry the richer product story:

- purpose and deterministic boundary
- toy flow, step by step
- parameters a user could change and how behavior would differ
- example internal data structures and accepted outputs
- behavior in different deployment or risk settings
- expected artifacts
- failure scenarios and likely diagnostics
- bigger-picture relevance for building scripts with Accentor
- honest limits, future capabilities, and package API pressure

## Rules

Use the `accentor/` package source as the current API source of truth.

Do not add implementation stubs for Accentor internals. These examples assume
the package exists and show how a user would call it.

ACO and CAO remain tutorial vocabulary. They should not appear as public module
paths, decorators, or class names.

When an example needs a richer failure story, put that narrative in the README
unless the failure path is essential to understanding the primary API.

## Next Examples To Add

Do not add every possible example at once. The most useful next focused example
is likely `08_artifact_promotion/` because it forces concrete decisions around
staged outputs, validation gates, provenance, and accepted project state.
