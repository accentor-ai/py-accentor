# PII-Filtered Draft

**What this demonstrates:** Privacy boundary — redact before dispatch, validate
after dispatch.
**Run:** `python example.py` (uses `CodexCli` — live provider)
**Expected output shape:**
```json
{"reply": "Thanks for reporting the duplicate charge. ..."}
```
**What to inspect afterward:** `redaction_report.json`, `redacted_input.txt`,
`validation_report_attempt_0.json`, `task_result.json`
**Tutorial prerequisite:** [03 Validators](../../tutorial/03_validators/),
[04 Agent Stage](../../tutorial/04_agent_stage/)

---

## Purpose And Boundary

This example places two deterministic boundaries around one agentic support
reply:

1. Conventional redaction before dispatch.
2. Output validation after dispatch.

The agent receives only the redacted note. The output gate then rejects obvious
PII-shaped content that the agent might repeat, guess, or invent.

## Toy Flow

1. `CUSTOMER_NOTE` contains an email, phone number, account ID, and amount.
2. `redact_note(...)` replaces matching values with stable tokens.
3. `draft_safe_response(...)` receives only the redacted text.
4. Validators require JSON and reject raw PII-shaped patterns.
5. `ContainsPhrase(field="reply", phrase="duplicate charge")` keeps the reply
   relevant, not merely privacy-safe.

## Parameters To Try

`PII_PATTERNS` is the main policy surface in this toy script. Adding a pattern
for names, addresses, order IDs, or dates would reduce what reaches the agent,
but regexes can also over-redact useful context.

The replacement tokens matter. `[EMAIL]` and `[ACCOUNT]` preserve enough context
for a support reply. A stricter workflow could replace every sensitive value
with `[REDACTED]`, but the agent would have less signal.

`ForbiddenPattern(...)` after dispatch should mirror the most important
redaction patterns. It cannot guarantee privacy, but it catches obvious leaks in
the generated reply.

`CodexCli(sandbox="read-only")` is enough because the agent only drafts text. If
the stage wrote a customer-facing artifact, file validators and artifact
promotion rules would become part of the boundary.

## Internal Data Shapes

The useful preprocessing artifact is a redaction report, not the raw note:

```json
{
  "stage": "redact_note",
  "patterns": [
    {"label": "email addresses", "count": 1, "token": "[EMAIL]"},
    {"label": "phone numbers", "count": 1, "token": "[PHONE]"},
    {"label": "internal account identifiers", "count": 1, "token": "[ACCOUNT]"},
    {"label": "exact dollar amounts", "count": 1, "token": "[AMOUNT]"}
  ]
}
```

The agent-facing input should look like this:

```text
Hi, this is regarding account [ACCOUNT]. My email is [EMAIL] and
you can also reach me at [PHONE]. I was charged twice for the same order
last week. The second charge is [AMOUNT]. Please help.
```

An accepted output is intentionally small:

```json
{
  "reply": "Thanks for reporting the duplicate charge. We will review the billing history and follow up with next steps."
}
```

## Behavior In Other Settings

For a helpdesk macro generator, this pattern can protect outbound drafts before
an agent sees raw customer data. For internal triage, the redaction could be
less aggressive if the agent runs in a trusted environment with stricter
observation controls. For healthcare, legal, or financial workflows, regex
redaction should be paired with named-entity detection, allowlisted fields, and
human review.

If the raw note must be retained for audit, it should go to a restricted
artifact store, not ordinary prompt logs or event streams.

## Expected Artifacts

```text
redaction_report.json
redacted_input.txt
prompt_attempt_0.md
validation_report_attempt_0.json
task_result.json
```

`redacted_input.txt` may contain tokens like `[EMAIL]` and `[ACCOUNT]`. It must
not contain the original email address, phone number, account ID, or exact
dollar amount.

## Failure Scenarios

If the agent outputs an email-like string, `ForbiddenPattern` rejects it.

If the agent outputs an account ID like `ACC-90412`, `ForbiddenPattern` rejects
it.

If the reply never mentions the duplicate charge, `ContainsPhrase` rejects it as
unhelpful even though it may be privacy-safe.

## Bigger Picture

Inspectability cannot mean persisting every raw input. This example shows why
Accentor needs observation policy as a first-class concept: teams need evidence
that redaction happened without scattering sensitive values through prompts,
events, and artifacts.

Candidate API concepts:

- `record_inputs=False`
- `sensitive_inputs=["raw_note"]`
- `ObservationPolicy(redact_inputs=True)`
- a redacted input serializer owned by the stage

## Ask Your Agent

This example is reference material for a coding agent to draft your own
redact-before-dispatch workflow. Point the agent here and describe your use case:

> See `examples/focused_examples/03_pii_filtered_draft/example.py` as
> reference. Write me an Accentor file for our healthcare helpdesk: redact
> patient names, MRNs, and dates of birth from incoming messages before
> dispatching to an agent for a draft reply. Validate that the output contains
> no MRN-shaped strings and mentions the reported symptom. The agent should
> never see raw patient identifiers.

Other prompts that use this pattern:

- "Draft an Accentor file for our HR onboarding system: redact SSNs and salary
  figures before the agent drafts a benefits summary, then validate the output
  has no SSN-shaped patterns."
- "Generate an Accentor file for a financial advisory workflow: strip account
  numbers and balances before the agent drafts a portfolio review note, and
  reject output containing any raw account identifiers."

## Limits

Regex gates catch obvious patterns. They do not detect contextual sensitivity,
names, or semantic PII. Privacy verification is a future capability.
