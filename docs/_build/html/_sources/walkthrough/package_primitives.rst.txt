Package Primitives
==================

Accentor is a library, not a framework. You call it from ordinary Python; it
does not own your process, your event loop, or your deployment model.

The package is organized into five groups. Each one maps to a phase in the
lifecycle of a hybrid task — from defining the work, through planning and
executing it, to judging the output and recording what happened. This page
walks through why each group exists and how they relate.


``accentor.core`` — Define the Work
------------------------------------

Before anything runs, you need to say what the work *is*.

``core`` gives you the task model: what a unit of hybrid work looks like, what
stages it contains, and how those stages compose. A **task** is a named run
that produces a **TaskResult**. Inside a task, **stages** mark the boundaries
where execution switches between agentic and conventional code.

The two decorators you will use most are ``workflow(...)`` for the outer run
boundary and ``stage(...)`` for a named unit of work inside that workflow.
Stages can be sequenced, retried, gated, or routed — all expressed as ordinary
Python.

``core`` also defines the data that flows through a run: **events** (timestamped
records of what happened), **diagnostics** (structured findings from validators),
**results** (the final envelope with ``ok``, ``output``, ``best_output``, and
everything needed for inspection), and **phases** for multi-step tasks like
read verification.

**Why it matters:** without ``core``, there is no shared vocabulary for what a
hybrid task is. Stages, events, diagnostics, and results are the primitives
that the rest of the package operates on.


``accentor.configure`` — Plan the Dispatch
------------------------------------------

Once you have defined a stage, something needs to assemble everything the agent
will need before it runs.

``configure`` turns user intent into an agent-agnostic **dispatch plan**: the
prompt material, the selected context, the workspace and permission intent, and
the success criteria rendered from your validators. The plan captures *what*
should be sent to an agent — not how a specific provider will execute it.

This separation matters because the same stage definition should work with
``MockAgent`` in tests, ``CodexCli`` in local development, and future adapters
like Claude Code or Gemini. ``configure`` makes that possible by resolving the
plan before any provider-specific code runs.

**Why it matters:** if you bake prompt assembly into dispatch, every new adapter
needs to reimplement context selection and criteria rendering. ``configure``
ensures the planning logic is shared and testable.


``accentor.dispatch`` — Execute Under Constraints
--------------------------------------------------

``dispatch`` binds a plan to a concrete provider adapter and enforces runtime
policy.

**Adapters** are the provider-specific code: ``MockAgent`` returns scripted
responses for tests and development; ``CodexCli`` wraps the installed ``codex``
executable via subprocess. Both implement the same contract, so swapping
providers does not change your task logic. The adapter-contract example
(``06_adapter_contract``) exercises this directly.

**Policy** is where actual runtime constraints live — not in prompt instructions.
Dispatch policy declares which files the agent may read or edit, which commands
it may run, what network access it has, and what environment variables are
visible. The workspace subsystem stages files for the agent, enforces diff-scope
checks, and manages revocation for multi-phase tasks.

**Routing** records are also part of dispatch: which context bundle was selected,
which candidates were considered, and the rationale.

**Why it matters:** prompt instructions are requests, not boundaries. Dispatch
and workspace policy are where you actually constrain what the agent can do.


``accentor.evaluate`` — Judge the Output
-----------------------------------------

After the agent responds, something needs to decide whether the output is
acceptable.

``evaluate`` has three layers:

**Expose** extracts structured output from raw agent responses. An agent might
return JSON wrapped in markdown fences, or prose with an embedded object —
expose normalizes this into something validators can check.

**Validation** runs deterministic checks against the exposed output: JSON shape,
required keys, text patterns, forbidden content, file existence, allowed values,
and custom checks via a lightweight ``check(output) -> list[str]`` adapter.
Validators are dual-purpose: they tell the agent the success criteria *before*
dispatch (via ``inject_criteria``), and they deterministically verify those
criteria *after* dispatch. When validation fails, the diagnostics become the
remediation prompt for the next attempt.

**Why it matters:** without ``evaluate``, there is no acceptance boundary. The
agent's output would enter the system based on confidence, not evidence.


``accentor.record`` — Preserve the Trail
-----------------------------------------

Every task run produces artifacts. ``record`` makes the run inspectable after
the fact.

**Observe** writes timestamped JSONL event streams: every stage entry and exit,
every prompt sent, every response received, every validation report. The
observation sink is pluggable — the default is filesystem JSONL, but the
contract is open for future backends.

**Artifacts** stores the concrete outputs of a run: prompt files, agent
responses, validation reports, result envelopes, and any promoted deliverables.
Artifact promotion is explicit — a validated output can be promoted to a
downstream location, but only through a declared path.

Failure records matter as much as success records. A failed run still preserves
the best available output, the diagnostics that explain why it could not be
accepted, and the full event trail. This is what makes hybrid tasks debuggable:
you can always see what the agent saw, what it proposed, and where conventional
checks rejected it.

**Why it matters:** agentic work is only trustworthy in production if you can
inspect it after the fact. ``record`` is what makes that possible.


How They Fit Together
---------------------

A typical run flows through the package in order:

.. code-block:: text

   core          — define the task and its stages
   configure     — assemble the dispatch plan
   dispatch      — execute via an adapter under policy constraints
   evaluate      — expose, validate, and optionally verify the output
   record        — write events, artifacts, and the result envelope

Each group depends on the ones before it but not the ones after. ``core``
defines the vocabulary; ``configure`` uses it to plan; ``dispatch`` executes
the plan; ``evaluate`` judges the output; ``record`` preserves everything.

The API reference pages document each module in detail. This page is the
narrative overview — the story of why these five groups exist and how a hybrid
task moves through them.

.. seealso::

   The `tutorial <https://github.com/accentor-ai/py-accentor/tree/main/examples/tutorial>`_
   in ``examples/tutorial/`` teaches these primitives hands-on. Each of the
   eight modules maps to concepts from the package groups above — starting
   with ``TaskResult`` (core), building through validators (evaluate) and
   agent dispatch (dispatch), and finishing with artifacts and events (record).
   Work through the tutorial to see the primitives in action before diving
   into the API reference.
