Why Accentor
============



LLM-powered agents changed what a software process can do. Code authorship,
analysis, report generation, ambiguous requirement interpretation, and adaptive
tool use can now be performed by agentic systems rather than only by humans or
deterministic scripts.


That creates a new design problem. Agentic processes are powerful, but they are
fragile in ways conventional software is not:

- They can hallucinate plausible but wrong APIs, facts, code, or dependencies.
- They are vulnerable to prompt injection and indirect instruction attacks.
- They degrade when context is too large, irrelevant, or poorly selected.

Conventional software has the opposite shape. It is deterministic,
reproducible, testable, and inspectable, but it cannot interpret ambiguous
intent or invent novel solutions.

Accentor is about composing these two modes deliberately.





Hybridization
-------------

Hybridization means designing a task where agentic and conventional components
operate together with explicit handoff points and assurance mechanisms.

**Conventional software process**
   A deterministic execution: scripts, CI pipelines, database migrations,
   parsers, validators, tests, artifact promotion, and policy checks.

**Agentic software process**
   An agent execution: prompt intake, model inference, tool use, adaptation,
   repair, and artifact production.

Accentor treats two process types as first-class:

The point is not to replace one with the other. The point is to decide where
each belongs.

Examples:

- Let an agent draft a report, but accept it only after deterministic citation
  and format checks.
- Let conventional code run an ETL job, but ask an agent for scoped repair after
  a deterministic schema failure.
- Let a router choose the relevant policy or code brief before an agent sees
  the task.
- Let a verifiability primitive check a narrow agentic claim using deterministic
  evidence.

Accentor provides the Python layer for these boundaries: tasks, stages,
validators, dispatch plans, permission scopes, workspaces, artifacts,
diagnostics, and recorded results.


Who It Is For
-------------

Accentor is for developers who already trust conventional Python tooling and do
not want to give it up. The intended user is comfortable with tools like
pytest, pydantic, pandas, subprocesses, and CI, but also wants to use agents for
the work that deterministic software cannot do well.

Accentor is strongest today for:

- repeatable workflows whose shape is mature enough to codify;
- high-sensitivity workflows where agentic output needs oversight;
- conventional systems that need scoped agentic assistance when they encounter
  situations they were not built to handle.
- interaction-driven development — build a GUI skeleton with buttons and upload
  fields before the logic exists, then let a coding agent observe how users
  engage with the interface and write the backing code for exactly the
  situations that arise. [#interactiondriven]_

.. [#interactiondriven] This is a development cycle where the agent is not
   prompted by text but by user engagement with the software itself. A
   developer — or someone who only vibe-codes — builds out the full
   interaction surface first: forms, buttons, file uploads, navigation. None
   of it does anything yet. Then a coding agent receives the trace of what
   the user clicked, uploaded, or submitted, and writes the implementation
   for exactly those paths. The skeleton becomes a specification; the agent
   fills it in. This inverts the usual flow where prompts precede interfaces
   and is a natural fit for Accentor's hybrid model: the GUI is conventional
   infrastructure, the agent authors the logic, and validators ensure the
   result meets the contract before it goes live.

It is not primarily a replacement for open-ended chat or interactive coding
sessions. Those may become adjacent surfaces later, but the first shape is a
library for explicit hybrid processes.
