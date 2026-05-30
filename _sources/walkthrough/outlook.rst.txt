Outlook
=======

Accentor is in alpha. This page is an account of what the current
release delivers, what it does not, and where the project is heading.


What the Alpha Delivers
-----------------------

The current alpha is an inspectable hybrid-task library. 

The delivered surface includes:

- ``@workflow(...)`` and ``@stage(...)`` as the primary user-facing API.
- ``TaskResult`` with ``ok``, ``output``, ``best_output``, ``diagnostics``,
  ``attempt_count``, ``events``, ``artifacts``, and raw-output helpers.
- Deterministic JSON, text, file, and custom validators with automatic criteria
  injection and remediation prompts.
- Intra-task routing with recorded decisions and rationale.
- Local workspace staging, revocation, diff-scope checks, and export.
- JSONL observation and filesystem artifact storage.
- ``MockAgent`` for deterministic testing and development.
- ``CodexCli`` as a thin subprocess adapter around the installed ``codex``
  executable.
- Multi-phase tasks with workspace revocation.
- Graceful expected-failure records.

Focused examples demonstrate these capabilities across structured output,
citation-constrained summaries, PII-filtered drafts, intra-task routing,
exception repair, and adapter contracts.


What the Alpha Does Not Include
-------------------------------

The alpha intentionally leaves out:

- **Additional provider adapters.** Only ``MockAgent`` and ``CodexCli`` ship
  today. Adapters for Claude, Gemini, and other providers are a near-term
  priority — the adapter contract (``06_adapter_contract``) already defines
  the runtime interface they will implement.
- **A library of reusable unit steps.** Today you compose stages by hand.
  A library of domain-specific steps — handling Excel data, parsing common
  file formats, interacting with specific APIs — would make composition
  faster. This is planned but not yet started.
- **Required high-level dependencies.** Pydantic, pandas, LangSmith,
  OpenTelemetry, Docker, gVisor, Firecracker, and ``jsonschema`` are not
  required. Accentor uses only the Python standard library and a small set
  of lightweight packages.
- **LangChain, DeepAgents, or other agent-framework integrations.**
- **Custom filesystem sandbox runtimes.**
- **Broad task-router frameworks.**
- **Cryptographic attestation** and challenge-based verification.


Where We Might Go
-------------------

These are directions we are actively thinking about, roughly ordered by how
soon they might become real.

**Provider swapping.** The adapter contract is designed to make it
straightforward to add Claude, Gemini, and other providers alongside Codex CLI.
The goal is that swapping providers is a one-line change in your stage
definition, with the same validators, workspace policy, and artifact recording
working identically regardless of which provider runs.

**Composite patterns.** ACO and CAO are single-boundary patterns, but real
workflows often chain multiple stages into directed graphs — mixing agentic and
conventional steps, branching on routing decisions, and feeding outputs forward.
This kind of multi-step composition is supported today but not yet formalized.
Investigating which composite shapes recur across domains and codifying them as
named patterns is an active direction.

**A step library.** Common operations — parsing structured files, calling
external APIs, transforming data — should eventually be available as composable
steps that integrate with Accentor's validation and artifact recording. These
would be domain-aware building blocks that make it faster to assemble workflows
without writing everything from scratch.

**Interactivity.** Today, Accentor dispatches work through a Python process.
The workflow runs, the agent responds, validators check the output, and the
result comes back. There is no interactive loop — no way to pause a run, inspect
intermediate state, and guide the next step from inside an editor or notebook.

This is a significant limitation. A custom IDE extension or notebook integration
could make Accentor's validation, artifact recording, and workspace features
available inside interactive coding sessions — where much of the real
development work happens today. This is a hard design problem but a highly
desirable one.

**Beyond Python.** Accentor is a Python library, and the focused examples are
Python files. But there is no fundamental reason hybridization needs to stay
within one language. Conventional tools in other languages — R scripts, shell
pipelines, compiled executables — could participate in hybrid tasks if the
dispatch and validation interfaces were language-neutral. This is a longer-term
direction, not a near-term plan.

**Companion applications.** Accentor workflows run as library calls today.
Companion applications — a GitHub App that runs intake pipelines on new issues,
a Slack bot that triggers triage workflows, a dashboard that shows run history
and artifact trails — would make hybrid tasks accessible to users who are not
writing Python. These are natural extensions of the conventional-invocation
pattern described in :doc:`before_invoking`.


Contributing
------------

Accentor is an open-source project and the community is a central part of
where it goes from here. Whether you want to add a provider adapter, build
a focused example for your domain, improve the docs, or just try the library
and report what surprised you — contributions are welcome and valued.

See `CONTRIBUTING.md <https://github.com/accentor-ai/py-accentor/blob/main/CONTRIBUTING.md>`_
for development setup, testing conventions, and guidelines.
