Accentor
========

*One who sings with another* — a Python library for harmonizing agentic and conventional software.

|
|

The software landscape has changed dramatically with the arrival of LLMs.
Most software now lives at one of two ends of a spectrum, and each has its own
vulnerabilities:

- **Agentic processes** are versatile but fragile. They hallucinate, drift
  from instructions, and produce outputs that are difficult to validate or
  reproduce. The more autonomous the agent, the harder it is to trust a
  given run.

- **Conventional processes** are reliable but rigid. They break when inputs
  arrive in an unexpected shape, when requirements shift, or when the task
  demands judgment that no amount of branching logic can anticipate —
  especially when those inputs come from humans or other agents rather than
  from well-typed upstream software.

Looked at together, these weaknesses are remarkably complementary. What
agents lack — structure, validation, reproducibility — is exactly what
conventional code provides. What conventional code lacks — adaptability,
interpretation, graceful handling of the unexpected — is exactly what agents
provide. Accentor is built on this observation: hybridizing the two paradigms
in a single pipeline lets each strengthen the other. [#hybridization]_

.. [#hybridization] An AI agent is not "purely agentic" in any absolute
   sense — internally it already uses conventional software. It makes tool
   calls, reads files through standard APIs, and operates inside sandboxes
   built from conventional infrastructure. But that internal hybridization is
   *general-purpose*: designed by providers like OpenAI and Anthropic to make the agent broadly
   capable, not tailored to your data contracts, validation requirements, or
   failure modes. Accentor lets you introduce *use-case-specific* — and even
   dynamically configured — hybridizations on top, so the boundaries serve
   your task.
   See :doc:`walkthrough/composition_patterns` for more on
   pure agentic, pure conventional, and the hybrid space between them.

Using These Docs
----------------

:doc:`getting_started` walks you through installation, shows you how to write
your first hybrid task, and explains the intended workflow — where a coding
agent drafts Accentor files and you review them.

The **Walkthrough** section builds the conceptual picture.

:doc:`walkthrough/why_accentor` makes the case that agentic and conventional
software have complementary failure modes. Agents hallucinate, drift, and
resist inspection. Conventional code is brittle, literal, and unable to
interpret ambiguous intent. Accentor treats hybridization not as a
compromise between the two but as a deliberate composition — you declare
where each mode belongs, and the handoff points are where the value
concentrates.

:doc:`walkthrough/before_invoking` is about the software processes that
surround an Accentor file — the ones that make it useful in practice. An
Accentor workflow is a Python function call that returns a result. That means
any surface that can call a function can invoke hybrid work: a GitHub Action,
a webhook, a cron job, an email listener, a queue consumer. None of that
requires agent-specific hosting or an interactive session. The page also
covers the authorship side — coding agents can draft Accentor files from
focused examples, so the library is designed to be written *by* agents and
invoked *by* conventional infrastructure. Both halves matter: agents produce
disciplined workflows, and conventional software invokes them reliably.

:doc:`walkthrough/composition_patterns` is the core design reference.
Hybridization occurs across a spectrum, and the page anchors it with two
patterns at either end — Agentic with Conventional Oversight (ACO), where
the agent produces, validators decide, and failed
attempts feed diagnostics back as remediation prompts for the next try, and
Conventional with Agentic Oversight (CAO), where deterministic code runs the
pipeline and agents appear only at declared failure boundaries. The page also
covers routing as a composition move for selecting context before dispatch,
and routing as a composition move for selecting context before dispatch.

:doc:`walkthrough/package_primitives` maps those patterns onto the library's
five package groups — core, configure, dispatch, evaluate, and record —
explaining what each one does, why it exists, and how they connect across the
lifecycle of a hybrid task. The
`tutorial <https://github.com/accentor-ai/py-accentor/tree/main/examples/tutorial>`_
in ``examples/tutorial/`` is a hands-on companion: it teaches each primitive
step by step with mock agents, so you can run everything locally.

:doc:`walkthrough/outlook` covers what the current alpha delivers, what is
coming next — more provider adapters, a composable step library,
interactivity, and companion applications — and how to get involved.
Accentor is open source and community-driven; the Outlook page links to
``CONTRIBUTING.md`` for anyone who wants to help shape what comes next.

The **API Reference** provides per-module documentation generated from the
source. Each package group has its own index page with links to individual
modules — :doc:`api_reference/core/index` for the task model,
:doc:`api_reference/dispatch/index` for adapters and runtime policy,
:doc:`api_reference/evaluate/index` for validators and extraction, and
:doc:`api_reference/record/index` for event streams and artifact storage.


Navigating the Repository
-------------------------

**Source package** — ``accentor/`` contains the library itself, organized
into five module groups: ``core`` (task model), ``configure`` (prompt
compilation), ``dispatch`` (provider adapters and runtime policy),
``evaluate`` (validators and extraction), and ``record`` (event streams
and artifact storage). The :doc:`walkthrough/package_primitives` page maps
these onto the composition patterns; the
`tutorial <https://github.com/accentor-ai/py-accentor/tree/main/examples/tutorial>`_
teaches each primitive hands-on with mock agents.

**Examples** — ``examples/`` is organized into two layers. The
`tutorial <https://github.com/accentor-ai/py-accentor/tree/main/examples/tutorial>`_
(``examples/tutorial/``) teaches Accentor primitives step by step with mock
agents — start here if you are new. The
`focused examples <https://github.com/accentor-ai/py-accentor/tree/main/examples/focused_examples>`_
(``examples/focused_examples/``) are capability recipes that apply those
primitives in realistic use cases — each pairs a compact ``example.py`` with
a README covering boundary narratives, failure scenarios, and sample prompts.

**Tests** — ``tests/`` contains the pytest suite. All tests are
deterministic and offline — no API keys or network access required. Run
``pytest`` to verify your setup. See ``CONTRIBUTING.md`` for testing
conventions.

**Documentation** — ``docs/`` (this site). Built with Sphinx. Build
locally with ``sphinx-build -b html docs docs/_build/html``.

**Key top-level files** —
``CONTRIBUTING.md`` (development setup and community norms),
``CHANGELOG.md`` (release history),
``LICENSE`` (MIT),
and ``pyproject.toml`` (package metadata and build configuration).


.. toctree::
   :hidden:
   :caption: Getting Started

   getting_started

.. toctree::
   :hidden:
   :caption: Walkthrough

   walkthrough/why_accentor
   walkthrough/before_invoking
   walkthrough/composition_patterns
   walkthrough/package_primitives
   walkthrough/outlook

.. toctree::
   :hidden:
   :caption: API Reference

   api_reference/core/index
   api_reference/configure/index
   api_reference/dispatch/index
   api_reference/evaluate/index
   api_reference/record/index

