Before Invoking Accentor
========================

Accentor's runtime value comes from hybrid execution. But there is also value
before execution: how hybrid pipelines are authored and how they are invoked.


Agentic Authorship
------------------

An Accentor workflow is a Python file. That makes it a good target for coding
agents.

The user should be able to describe a desired hybrid process:

- what the agent should produce;
- what conventional checks must accept;
- what files or data the agent may see;
- what artifacts should be promoted;
- what failures should trigger remediation or repair.

An Accentor-aware coding agent can then draft the task, stages, validators,
permissions, routing, and result handling. The developer reviews the output
like any other code.

In practice, this means pointing a coding agent at a focused example and
describing your workflow:

    *"See the structured output example as reference. Write me an Accentor file
    that receives customer escalation tickets, has an agent draft a triage
    record, and validates it against required fields and forbidden patterns."*

The focused examples in ``examples/focused_examples/`` each include sample
prompts like this. If the agent also has access to ``SKILL.md``, it should be
able to produce a use-case-specific Accentor file from a short prompt.

This is an upstream uplift: agents help author disciplined agentic-conventional
pipelines before those pipelines ever run.


Conventional Invocation
-----------------------

An Accentor workflow is a Python function call that returns a ``TaskResult``.
That means any software surface that can call a function can invoke hybrid
agentic-conventional work — no special runtime, no agent-specific hosting, no
interactive session required.

The surfaces that already exist in most organizations are exactly the ones that
work:

- a **GitHub Action** runs an Accentor workflow on every pull request, validating
  agent-drafted code against project conventions before a human reviewer sees it;
- a **webhook** triggers a repair or review pipeline when a monitoring alert
  fires;
- a **web application endpoint** starts a report-generation task when a user
  submits a form;
- a **cron job** runs a recurring analysis overnight and promotes validated
  artifacts to a shared drive;
- a **filesystem watcher** or editor hook runs a local validation workflow every
  time a file changes;
- a **background worker** routes operational incidents into scoped repair tasks
  pulled from a queue.


Even **email** works. IMAP polling, filtering rules, and attachment extraction
are mature conventional infrastructure. Wire them to an Accentor workflow and
anyone in the organization can invoke disciplined agentic work by sending a
message — no CLI, no deployment, no interactive session. The result comes back
as a reply or lands in a ticketing system. Hybrid agentic software, at your
fingertips.

The broader point: conventional software already knows how to receive requests,
route them, authenticate senders, and deliver results. Accentor sits inside
those surfaces as the layer that makes the agentic part inspectable, bounded,
and repeatable. The invocation surface is ordinary software. The agentic
contribution is contained inside a declared boundary. And every prompt,
response, and validation report is recorded.


The Combined Shape
------------------

Agents help write the Accentor files. Conventional software invokes them.
Accentor sits between those two surfaces as the library that makes the hybrid
process inspectable, bounded, and repeatable.

That framing matters because it makes existing tools feel more powerful:

- coding agents become authors of disciplined workflows, not only ad hoc code;
- CI, web apps, queues, and hooks become invocation surfaces for agentic work;
- validators, workspaces, artifacts, and diagnostics become feedback signals for
  improving prompts, package APIs, and operational policy.

As Accentor matures, this shape scales to richer systems — web applications
where each endpoint is backed by a validated Accentor workflow:

- A **customer-facing chatbot** that never hallucinates policy — validators
  enforce that every response cites an approved source document.
- A **media production service** where users upload raw footage and receive
  transcoded deliverables — the agent chooses the transcode plan, FFmpeg
  executes it, file validators confirm the output.
- A **lab data portal** where researchers submit experimental results and get
  back validated analysis reports — the agent drafts the analysis code,
  deterministic checks own the numbers.
- A **legal intake tool** that organizes unstructured case documents into
  structured summaries — validators require source references and block
  unsupported claims.
- A **CI companion** that reviews pull requests against project conventions —
  the agent reads the diff, validators enforce that findings reference real
  lines in real files.