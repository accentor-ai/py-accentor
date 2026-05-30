# Accentor

*One who sings with another* — a Python library for harmonizing agentic and conventional software.

**[Read the docs!](https://accentor-ai.github.io/py-accentor/dev/)**

Agentic processes are versatile but fragile — they hallucinate, drift from instructions, and produce outputs that are hard to validate. Conventional processes are reliable but rigid — they break when inputs arrive in an unexpected shape or when the task demands judgment. These weaknesses are complementary. Accentor composes both paradigms in a single pipeline so each strengthens the other.

## Installation

Accentor is not yet on PyPI — a published package is coming soon. For now, install from a local clone:

```bash
git clone https://github.com/accentor-ai/py-accentor.git
cd py-accentor
pip install -e .
```

## Quick Look

**Discipline an agent** — wrap agentic output with deterministic validators so it is accepted only when it meets a contract:

```python
from accentor.core.decorators import stage, workflow
from accentor.dispatch.agents.providers.codex_cli import CodexCli
from accentor.evaluate.validation import (
    JsonRequired, NoMarkdownFences, TitleMaxWords,
)

@stage(
    name="draft_triage_record",
    agent=CodexCli(sandbox="read-only"),
    validators=[
        NoMarkdownFences(),                                     # no ```json fences
        JsonRequired(keys=["title", "summary", "severity"]),    # must have these keys
        TitleMaxWords(field="title", max_words=10),             # keep titles concise
    ],
    max_attempts=2,       # retry once on validation failure
    inject_criteria=True, # tell the agent what "good" looks like before it runs
)
def draft_triage(ticket: str, success_criteria: str = "") -> str:
    """Build the prompt sent to the agent."""
    return f"Triage this support ticket.\n\n{success_criteria}\n\n{ticket}"

@workflow(name="triage")
def triage() -> dict:
    return draft_triage("User sees a blank screen after login on Safari 17.")
```

**Make conventional code more robust** — add scoped agent repair so a deterministic pipeline can recover from unexpected inputs:

```python
from pathlib import Path
from accentor.core.decorators import stage, workflow
from accentor.dispatch.agents.providers.codex_cli import CodexCli
from accentor.evaluate.validation import RequiredFile

OUTPUT = Path("output/report.json")

@stage(
    name="parse_input",
    readable=[Path(__file__), Path("data/input.csv")],  # agent can read these
    editable=[Path(__file__)],                           # agent can edit this
    on_error={
        ValueError: {                                    # only this error triggers repair
            "response": "agent_repair",
            "agent": CodexCli(sandbox="workspace-write"),
            "goal": "Fix the parsing so the pipeline completes.",
            "validators": [RequiredFile(OUTPUT)],        # repair must produce this file
        }
    },
)
def parse_input(path):
    # your deterministic parsing logic goes here
    # if it raises ValueError, an agent gets a scoped repair attempt
    ...
```

Every workflow returns a `TaskResult` with `ok`, `output`, `diagnostics`, and a full artifact trail on disk.

## Package Structure

| Module | Purpose |
|---|---|
| `accentor.core` | Task model — workflows, stages, events, results |
| `accentor.configure` | Prompt compilation and agent-agnostic dispatch plans |
| `accentor.dispatch` | Provider adapters and runtime policy (workspace, permissions) |
| `accentor.evaluate` | Validators and output extraction |
| `accentor.record` | JSONL event streams, artifact storage, result envelopes |

## Composition Patterns

Accentor defines two foundational patterns for hybrid processes:

**ACO (Agentic with Conventional Oversight)** — the agent produces, conventional code validates. Useful when the task requires judgment but the output must meet a deterministic contract.

```
prepare context → dispatch agent → expose output → validate → result
                                                       ↓ fail
                                                   remediate → retry
```

**CAO (Conventional with Agentic Oversight)** — conventional code runs the pipeline, the agent appears only on declared failures. Useful when the workflow is reliable most of the time and the painful cases are just outside the existing contract.

```
run pipeline → catch declared failure → scoped agent repair → verify → rerun → result
```

Both patterns can be combined with **routing** (selecting context before dispatch).

## Repository Layout

```
accentor/                       ← the library
examples/
  focused_examples/             ← 6 numbered capability recipes (start here)
tests/                          ← pytest suite (deterministic, offline)
docs/                           ← Sphinx source (deployed at accentor-ai.github.io/py-accentor)
```

**Focused examples** are the best way to learn the library. Each directory contains an `example.py` (compact usage sketch) and a `README.md` (boundary narrative, failure scenarios, and a sample prompt for agent-authored variants). Read them in numeric order:

| # | Example | Pattern |
|---|---|---|
| 01 | Structured Output | ACO with JSON validation |
| 02 | Citation-Constrained Summary | Source-derived constraints before dispatch |
| 03 | PII-Filtered Draft | Conventional redaction before and after the agent |
| 04 | Intra-Task Routing | Context routing before dispatch |
| 05 | Exception Repair | CAO with scoped agent repair |
| 06 | Adapter Contract | Provider swapping behind a shared runtime contract |

## Authoring Workflows

Accentor `.py` files are designed to be authored by coding agents. Show a coding agent one of the focused examples, describe what you need, and the agent drafts an Accentor file for your use case. Each example README includes sample prompts.

## Documentation

Full walkthrough and API reference are available at **[accentor-ai.github.io/py-accentor/dev](https://accentor-ai.github.io/py-accentor/dev/)**:

- [Getting Started](https://accentor-ai.github.io/py-accentor/dev/getting_started.html) — installation, first task, reading results
- [Why Accentor](https://accentor-ai.github.io/py-accentor/dev/walkthrough/why_accentor.html) — the case for hybridization
- [Composition Patterns](https://accentor-ai.github.io/py-accentor/dev/walkthrough/composition_patterns.html) — ACO, CAO, and routing
- [Package Primitives](https://accentor-ai.github.io/py-accentor/dev/walkthrough/package_primitives.html) — the five module groups
- [API Reference](https://accentor-ai.github.io/py-accentor/dev/api_reference/core/index.html) — per-module documentation

## Testing

The test suite in [`tests/`](tests/) uses pytest and is fully deterministic and offline — no API keys or network access required.

```bash
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for testing conventions and mock-agent requirements.

## Contributing

Accentor is open source and the community is a central part of where it goes from here. There is plenty of room to make an impact — adding provider adapters, writing focused examples for new domains, improving documentation, building companion applications, or simply trying the library and sharing what you learn.

If any of that sounds interesting, we would love to have you. [CONTRIBUTING.md](CONTRIBUTING.md) covers development setup, branching model (`dev` is the integration branch — all PRs target `dev`), testing conventions, and pull request guidelines.

**Reporting issues** — use the templates in [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) for [bug reports](.github/ISSUE_TEMPLATE/bug_report.md), [feature requests](.github/ISSUE_TEMPLATE/feature_request.md), and [reliability reports](.github/ISSUE_TEMPLATE/reliability_report.md).

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release history.

## License

MIT — see [LICENSE](LICENSE).
