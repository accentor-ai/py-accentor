Composition Patterns
====================

Most software today is either purely conventional or purely agentic. Accentor
exists because neither extreme is enough, and the interesting space is in how
you combine them.

.. figure:: ../figures/composition_spectrum.png
   :width: 90%
   :align: center

   The composition spectrum — from purely conventional to purely agentic, with
   hybrid compositions in between.


Pure Conventional
-----------------

A conventional process is deterministic. Same input, same output, every time.
It is testable, auditable, and predictable.

It is also brittle. When inputs arrive in an unexpected shape, when
requirements shift, or when the task demands judgment that branching logic
cannot anticipate, a conventional process either fails or waits for a human.


Pure Agentic
------------

An AI agent is not "purely agentic" in any absolute sense — internally it
already uses conventional software. It makes tool calls, reads files through
standard APIs, and operates inside sandboxes built from conventional
infrastructure.

But that internal hybridization is *general-purpose*. It is designed by the
provider to make the agent broadly capable across many users and tasks. It is
not tailored to your data contracts, your validation requirements, or your
failure modes.

When Accentor says "purely agentic," it means: from your perspective, the
agent is a black box. You call it and get output. Accentor lets you add
*use-case-specific* hybridization on top — constraining agent behavior in
ways that matter for your particular task.

A purely agentic process is adaptive. It can handle ambiguous intent, novel
inputs, and situations it was not programmed for. It is also unreliable — it
can hallucinate, drift from instructions, and produce confident explanations
of things it got wrong. There is no built-in acceptance boundary.


The Hybrid Space
----------------

Hybridization means declaring where each mode belongs inside a single task.
The agent handles the parts that require adaptation and judgment. Conventional
code handles the parts that require determinism and verifiability. The boundary
between them is explicit and enforceable.

This is not a compromise. It is a composition — each side does what it is best
at, and the handoff points are where the value concentrates.


Agentic With Conventional Oversight (ACO)
-----------------------------------------

In ACO, the agent is the primary producer. It drafts the output — a triage
record, a summary, a code artifact. Conventional code wraps that step with
discipline: preparing the input, constraining what the agent sees, validating
the output, and deciding whether to accept it.

.. figure:: ../figures/aco_flow.png
   :width: 85%
   :align: center

   ACO flow — conventional code prepares, the agent produces, validators
   decide.

The typical flow:

.. code-block:: text

   prepare context → dispatch agent → expose output → validate → result

The agent writes. Validators decide. If the output fails and retries are
configured, the diagnostics become the remediation prompt for the next
attempt. The caller never sees an unvalidated response.

Conventional discipline can appear at several points around the agentic step:

**Before dispatch** — redact sensitive fields, select the smallest relevant
context, derive validation criteria from the source material.

**After dispatch** — enforce schema, check for forbidden content, verify
citations, validate that expected files exist.

**On failure** — feed diagnostics back to the agent, or escalate to human
review.

**On success** — promote the validated artifact downstream and record the
full decision trail.

Use ACO when the task requires judgment or interpretation that conventional
code cannot provide — but the output must meet a deterministic contract before
it enters your system.


Conventional With Agentic Oversight (CAO)
-----------------------------------------

In CAO, the normal path is conventional. The pipeline runs deterministic code —
parsing, transforming, validating — and succeeds most of the time without any
agentic involvement.

The agent appears only at declared boundaries where conventional code
acknowledges it cannot handle the situation: an unexpected file layout, an
ambiguous input, a schema drift. The conventional system raises a specific
exception, and an agent is invited to diagnose or repair within a scoped
boundary.

.. figure:: ../figures/cao_flow.png
   :width: 85%
   :align: center

   CAO flow — conventional code runs the pipeline, the agent appears only
   on declared failures.

The typical flow:

.. code-block:: text

   run pipeline → catch declared failure → stage scoped repair → verify → rerun → result

The agent sees only the failure and the files you declare as editable. If the
repair passes validation and the pipeline succeeds on rerun, the agent's
contribution is accepted. Otherwise, the system fails safe with diagnostics.

Use CAO when the workflow is already reliable most of the time and the painful
cases are just outside the existing contract. The agent makes the conventional
system more versatile without surrendering ownership.


Routing As A Composition Move
-----------------------------

ACO and CAO are single-boundary patterns. In practice, workflows often chain
multiple stages into directed graphs — mixing agentic and conventional steps,
branching on routing decisions, and feeding the output of one stage into the
validators of the next. This kind of multi-step composition is supported today,
but investigating and formalizing useful composite patterns is an active
direction. See :doc:`outlook` for more on where this is heading.

Routing is not a third pattern. It is a composition move that improves either
ACO or CAO by selecting the right context before work begins.

When a task serves multiple domains — different support categories, different
policy documents, different validator sets — sending everything to the agent
degrades context quality. Routing selects the next branch, context bundle,
validators, or remediation path based on explicit inputs.

Routing should produce artifacts: which route was selected, which candidates
were considered, and the rationale. This matters for debugging and for
understanding why a particular run produced its output.


Focused Examples
----------------

The examples in ``examples/focused_examples/`` instantiate these patterns
concretely:

- ``01_structured_output`` — single ACO boundary with JSON validation
- ``02_citation_constrained_summary`` — source-derived constraints before dispatch
- ``03_pii_filtered_draft`` — conventional redaction before and after the agent
- ``04_intra_task_routing`` — context routing before dispatch
- ``05_exception_repair`` — CAO pattern with scoped agent repair
- ``06_adapter_contract`` — provider swapping behind a shared runtime contract

Each example pairs a compact ``example.py`` with a README that covers the
boundary narrative, expected artifacts, failure scenarios, and an example agent
prompt for generating a real-world variant.

If you are new to Accentor, the
`tutorial <https://github.com/accentor-ai/py-accentor/tree/main/examples/tutorial>`_
in ``examples/tutorial/`` teaches the underlying primitives (``TaskResult``,
stages, validators, agents, routing, artifacts) step by step with mock agents
before you explore these capability recipes.
