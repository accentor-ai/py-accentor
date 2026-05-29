# Structured Output

**What this demonstrates:** Deterministic validation gates between agent output
and application data.
**Run:** `python example.py` (uses `CodexCli` — live provider)
**Expected output shape:**
```json
{"title": "...", "summary": "...", "risks": [...], "next_steps": [...]}
```
**What to inspect afterward:** `task_result.json`, `validation_report_attempt_0.json`
**Tutorial prerequisite:** [03 Validators](../../tutorial/03_validators/),
[05 Extraction and Retry](../../tutorial/05_extraction_and_retry/)

---

## Purpose And Boundary

The agent writes the summary, but Accentor decides whether the output becomes
application data. The lesson is not "LLMs can produce JSON." The lesson is that
agent text should cross a deterministic boundary before a script treats it as a
normal Python object.

In `example.py`, the toy boundary accepts output only when it has:

- no Markdown fences
- JSON with `title`, `summary`, `risks`, and `next_steps`
- a title with at most 10 words
- a summary that says `customer impact`
- exactly two risks and three next steps
- no internal ticket IDs shaped like `CSV-4812`

## Toy Flow

1. `ISSUE_TEXT` provides one short product-support scenario.
2. `summarize_issue(...)` sends that scenario to `CodexCli`.
3. `inject_criteria=True` lets Accentor include validator requirements in the
   initial prompt and remediation prompts.
4. `JsonRequired(...)` exposes the agent response as JSON.
5. The remaining validators check the exposed object and raw text.
6. The workflow returns a `TaskResult` with either parsed `output` or
   diagnostics plus `best_output`.

## Parameters To Try

`CodexCli(sandbox="read-only")` means the agent is only drafting text. If the
stage needed to write files, the sandbox and permissions would need to change,
and the validators should also check those files.

`max_attempts=2` allows one remediation attempt after an invalid first response.
A lower value makes failures faster and easier to debug. A higher value may
improve acceptance rate, but it can hide a weak prompt if the same validator
fails repeatedly.

`inject_criteria=True` makes the acceptance contract visible to the agent. If it
were disabled, the validators would still enforce the same rules, but the prompt
would need to describe the shape and constraints manually.

The validators are ordinary policy choices. `ArrayLength(field="risks",
exactly=2)` could become `min_items=1, max_items=5` in a richer API. `TitleMaxWords`
could be replaced by a schema validator. `ContainsPhrase(...)` is useful for a
small demo, while production workflows often use more specific semantic or
domain validators.

## Internal Data Shapes

The stage configuration is conceptually a contract like this:

```json
{
  "stage": "summarize_issue",
  "agent": "CodexCli",
  "sandbox": "read-only",
  "max_attempts": 2,
  "validators": [
    "NoMarkdownFences",
    "JsonRequired(title, summary, risks, next_steps)",
    "TitleMaxWords(title <= 10)",
    "ContainsPhrase(summary contains customer impact)",
    "ArrayLength(risks == 2)",
    "ArrayLength(next_steps == 3)",
    "ForbiddenPattern(internal ticket IDs)"
  ]
}
```

After JSON exposure, the accepted internal object should look like normal
application data:

```json
{
  "title": "CSV Import Blank Plan Names",
  "summary": "Blank plan names create customer impact during onboarding...",
  "risks": [
    "Users repeatedly retry failed uploads.",
    "Support receives unclear import-failure tickets."
  ],
  "next_steps": [
    "Add a specific validation message.",
    "Document required CSV fields.",
    "Track failures by missing field."
  ]
}
```

A failed attempt should produce diagnostics rather than an opaque exception:

```json
{
  "stage": "summarize_issue",
  "attempt": 0,
  "ok": false,
  "diagnostics": [
    {
      "code": "markdown_fence",
      "message": "Output must not be wrapped in Markdown fences."
    }
  ]
}
```

## Behavior In Other Settings

For a CLI script, a failed result might print diagnostics and exit non-zero. For
a review dashboard, the same diagnostics could be grouped by validator name. For
a batch pipeline, invalid rows could be quarantined while valid rows continue.

If the issue text were much longer, the stage might add retrieval, chunking, or
source citations before this same output gate. If the downstream consumer were a
typed application service, `JsonSchema` or a Pydantic validator would be a
better fit than several small field validators.

## Expected Artifacts

```text
events.jsonl
prompt_attempt_0.md
agent_response_attempt_0.txt
expose_attempt_0.json
validation_report_attempt_0.json
remediation_prompt_attempt_1.md
task_result.json
```

## Failure Scenarios

If the agent returns fenced JSON, `NoMarkdownFences` rejects it and the
remediation prompt asks for raw JSON only.

If the agent invents `CSV-4812`, `ForbiddenPattern` rejects the output as an
internal ticket ID.

If the arrays have the wrong lengths, `ArrayLength` rejects the output before
the caller receives a parsed object.

## Bigger Picture

Structured-output gating is one of the simplest ways to put agents inside real
software without letting the first model response become application state. It
also gives teams measurable reliability data: which validators fail, how often
remediation succeeds, and which prompts repeatedly produce invalid objects.

## Ask Your Agent

This example is reference material for a coding agent to draft your own
structured-output workflow. Point the agent here and describe your use case:

> See `examples/focused_examples/01_structured_output/example.py` as reference.
> Write me an Accentor file that receives customer escalation tickets from our
> support portal, dispatches them to an agent for triage, and gates the output
> on JSON shape with required fields for severity, customer impact summary,
> evidence citations, and recommended next actions. Reject any output that
> contains unverified refund approvals or internal ticket IDs. The result should
> be ready for our review queue or return diagnostics for human review.

Other prompts that use this pattern:

- "Draft an Accentor file that takes a security incident report, asks an agent
  to produce a structured impact assessment, and validates that the output has
  exactly three risk items and no hallucinated CVE numbers."
- "Generate an Accentor file for our legal intake: the agent summarizes a
  client matter from scanned notes, and validators enforce required fields for
  jurisdiction, parties, relief sought, and evidence list."

## API Pressure

This example forces stable answers for:

- whether `JsonRequired(...)` implies default JSON extraction
- diagnostic code names for common validators
- remediation event and artifact names
- how `best_output` is represented after exhausted attempts
