Getting Started
===============

Setup
-----


Accentor is not yet on PyPI — a published package is coming soon. For now,
install from a local clone:

.. code-block:: bash

   git clone https://github.com/accentor-ai/py-accentor.git
   cd py-accentor
   pip install -e .

Or, if you use `uv <https://docs.astral.sh/uv/>`_ to manage your Python
environment:

.. code-block:: bash

   git clone https://github.com/accentor-ai/py-accentor.git
   cd py-accentor
   uv pip install -e .

Accentor requires **Python 3.13+** and has no dependencies beyond the
Python standard library.

.. note::

   For live LLM interaction, Accentor calls the
   `Codex CLI <https://github.com/openai/codex>`_ as a subprocess. Install
   the ``codex`` binary and make sure it is available on your ``PATH``:

   .. code-block:: bash

      npm install -g @openai/codex

   Codex CLI must be configured with a valid API key (see the Codex
   documentation for details). Without it, agent-backed stages will not be
   able to reach an LLM. You can still run all examples in offline/mock mode
   without Codex installed.

For development (running tests, building docs, contributing):

.. code-block:: bash

   git clone https://github.com/accentor-ai/py-accentor.git
   cd py-accentor
   uv venv && source .venv/bin/activate
   uv pip install -e ".[dev,docs]"

Run ``pytest`` to verify everything is working. See
`CONTRIBUTING.md <https://github.com/accentor-ai/py-accentor/blob/main/CONTRIBUTING.md>`_
for the full development setup.


Who Writes Accentor Files
-------------------------

Accentor ``.py`` files are designed to be **authored by coding agents**. The
focused examples in ``examples/focused_examples/`` are reference material: they
show the patterns, imports, and boundary conventions that an agent needs to
produce a working file for your use case.

The workflow is simple: show a coding agent one of the focused examples, describe
what you need, and the agent drafts an Accentor file for your use case. You
review, adjust, and run.

Each focused example README includes sample prompts to get started.


An Initial Task
---------------

Hybridization is the combination of agentic and conventional software
processes in a single pipeline — letting each strengthen the other at
explicit handoff points (see :doc:`walkthrough/composition_patterns` for the
full picture). Let's explore what an initial task at each end of the
spectrum looks like.

**Disciplining agentic behavior.** You have an agent producing useful output —
summaries, triage records, draft configs — but you cannot trust its first
response as data. Wrap the agentic step in a ``@stage`` with validators so the
output is accepted only when it satisfies a deterministic contract:

.. code-block:: python

   @stage(
       name="draft_triage",
       agent=CodexCli(...),
       validators=[JsonRequired(keys=["title", "summary", "severity"]), ...],
       max_attempts=2,
   )
   def draft_triage(ticket):
       return f"Triage this support ticket.\n\n{ticket}"

   @workflow(name="triage")
   def triage():
       return draft_triage("User sees blank screen after login on Safari 17.")

The agent writes; the validators decide. If the first attempt fails, Accentor
feeds the diagnostics back as a remediation prompt and retries. The caller
never sees an unvalidated response.

**Making conventional code more robust.** You have a deterministic pipeline
that works most of the time. When an unexpected input breaks it, an agent
gets a scoped repair attempt — but only for a declared error, only against
files you specify, and only if the fix passes your validators:

.. code-block:: python

   @stage(
       name="parse_input",
       readable=["data/input.csv"],
       editable=["data/input.csv"],
       on_error={
           ValueError: {
               "response": "agent_repair",
               "agent": CodexCli(...),
               "validators": [RequiredFile("output/report.json"), ...],
           }
       },
   )
   def parse_input(path):
       rows = csv.DictReader(open(path))
       for row in rows:
           if "amount" not in row:
               raise ValueError(f"Missing 'amount' column in {path}")
           ...

Conventional code owns the happy path. The agent only appears when the
``ValueError`` fires. The repair is bounded: the agent can only touch the
files you declare, and its fix must pass your validators before the pipeline
accepts it.

Running a Task and Reading the Result
-------------------------------------

Every Accentor workflow is an ordinary Python function. Call it and you get
back a ``TaskResult`` — a single object that tells you whether the task
succeeded, gives you the output, and explains what happened if it didn't:

.. code-block:: python

   result = triage()

   if result.ok:
       print(result.output)       # the validated object (e.g. parsed JSON dict)
   else:
       print(result.best_output)  # best attempt, even on failure
       for d in result.diagnostics:
           print(f"[{d.code}] {d.message}")

``result.ok`` is ``True`` only when every validator passed. When it is
``False``, ``diagnostics`` tells you exactly what failed and why — with
machine-readable codes and human-readable messages so you can branch on
failure programmatically or debug it yourself.

Accentor also writes a structured artifact trail to disk so every run is
inspectable after the fact:

- ``events.jsonl`` — timestamped log of every task event
- ``prompt_attempt_0.md`` — the prompt sent to the agent
- ``agent_response_attempt_0.txt`` — the raw agent output
- ``validation_report_attempt_0.json`` — which validators passed and failed
- ``task_result.json`` — the final result envelope

If the first attempt fails and Accentor retries, each subsequent attempt gets
its own numbered artifacts plus a ``remediation_prompt`` showing the feedback
the agent received. No output is lost, even on failure.

.. seealso::

   The `tutorial <https://github.com/accentor-ai/py-accentor/tree/main/examples/tutorial>`_
   teaches these primitives hands-on — starting with ``TaskResult`` fields in
   module 01 and building up through stages, validators, agents, extraction,
   routing, and artifacts. :doc:`walkthrough/package_primitives` provides the
   conceptual map of how these pieces fit together across the five package
   groups.


Bringing Accentor into Deployed Software
-----------------------------------------

Accentor workflows are ordinary Python. They run with ``python my_file.py``,
import like any module, and return a ``TaskResult`` that conventional code can
branch on. This means you can invoke hybrid agentic-conventional work from
any surface your software already has.

Consider a web application that receives a support ticket and needs a
validated triage record:

.. code-block:: python

   # app.py — a Flask endpoint that invokes an Accentor workflow
   from flask import Flask, request, jsonify
   from triage_workflow import triage_ticket

   app = Flask(__name__)

   @app.route("/triage", methods=["POST"])
   def handle_triage():
       ticket_text = request.json["ticket"]
       result = triage_ticket(ticket_text)

       if result.ok:
           return jsonify(result.output), 200
       else:
           return jsonify({
               "error": "Triage did not pass validation.",
               "diagnostics": [
                   {"code": d.code, "message": d.message}
                   for d in result.diagnostics
               ],
           }), 422

The endpoint is conventional — routing, authentication, rate limiting, error
responses are all standard web-application concerns. The agentic work is
contained inside ``triage_ticket``, which is an Accentor workflow with its own
validators, retry policy, and artifact trail. The web application never sees
an unvalidated agent response; it only sees a ``TaskResult`` that either passed
or explains why it didn't.

The same pattern applies to GitHub Actions, cron jobs, background workers,
CLI tools, and editor hooks. Accentor does not require a special runtime or
hosting model — it is a library call inside whatever invocation surface you
already operate.

.. seealso::

   :doc:`walkthrough/before_invoking` explores this idea further: agents author
   the workflows (agentic authorship), conventional infrastructure invokes them
   (conventional invocation), and Accentor sits between those surfaces as the
   layer that makes the hybrid process inspectable, bounded, and repeatable.
