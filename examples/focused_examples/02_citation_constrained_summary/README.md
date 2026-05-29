# Citation-Constrained Summary

**What this demonstrates:** Source-derived deterministic constraints that fence
in agentic prose — validators built from the same material the agent receives.
**Run:** `python example.py` (uses `CodexCli` — live provider)
**Expected output shape:**
```json
{"title": "...", "findings": ["... [source-label]", ...], "sources_used": [...]}
```
**What to inspect afterward:** `source_number_allowlist.json`,
`validation_report_attempt_0.json`, `task_result.json`
**Tutorial prerequisite:** [03 Validators](../../tutorial/03_validators/)

---

## Purpose And Boundary

The agent writes an executive summary, but deterministic constraints are derived
from the same source texts the agent receives. The boundary accepts prose only
when it keeps visible citations and does not introduce unsupported numbers.

This is intentionally not full semantic citation verification. It checks JSON
shape, source labels, sensitive patterns, phrase counts, and numeric literals.
It does not prove every claim follows from the cited source.

## Toy Flow

1. `SOURCE_A` and `SOURCE_B` contain short quarterly shipping excerpts.
2. `extract_numbers(...)` builds `ALLOWED_NUMBERS` before the agent runs.
3. `summarize_with_citations(...)` prompts the agent to return JSON only.
4. Generic validators enforce shape and citation-label presence.
5. `NumbersFromSources` rejects numeric literals absent from the source texts.
6. The workflow returns an accepted summary or evidence-bound diagnostics.

## Parameters To Try

`NUMBER_PATTERN` controls what counts as a numeric claim. In this toy setting it
matches values like `2.1`, `3.4`, and `87`. A production variant might normalize
percentages, currency, dates, ranges, table cells, or units.

`ContainsPhrase(field="findings", phrase="logistics-q3")` requires a source
label to appear somewhere in `findings`. A stricter version would make each
finding an object with its own `citations` array.

`ExactPhraseCount(field="findings", phrase="NPS", count=1)` is a small policy
gate for this example. In another report, the phrase could be optional or could
be replaced by a domain taxonomy check.

`ArrayLength(field="sources_used", exactly=2)` assumes both source snippets are
required. If a task had many candidate sources, a better rule might require at
least one source per claim and no unused citation labels.

## Internal Data Shapes

The source-derived allowlist is the key internal structure:

```json
{
  "allowed_numbers": ["2.1", "3.4", "40", "87", "71", "12"],
  "source_labels": ["logistics-q3", "cx-survey-q3"]
}
```

An accepted output is exposed as JSON:

```json
{
  "title": "Shipping Delays Hurt Customer Experience",
  "findings": [
    "Fulfillment time increased from 2.1 days to 3.4 days [logistics-q3].",
    "Delivery-speed satisfaction dropped from 87 percent to 71 percent, and logistics NPS fell 12 points [cx-survey-q3]."
  ],
  "sources_used": ["logistics-q3", "cx-survey-q3"]
}
```

A custom-validator rejection should stay narrow and inspectable:

```json
{
  "stage": "summarize_with_citations",
  "validator": "NumbersFromSources",
  "ok": false,
  "diagnostics": [
    {
      "code": "number_not_in_sources",
      "message": "Number not in source material: 95"
    }
  ]
}
```

## Behavior In Other Settings

For research notes, the same pattern could derive citation IDs from retrieved
documents. For analytics narratives, it could derive allowed metrics from a
query result. For regulated reports, the numeric validator would likely be
paired with exact source-span citations and reviewer signoff.

If sources contain tables or spreadsheets, regex extraction is too weak. The
validator should work from parsed cells and metadata so it can distinguish a
date, count, percentage, and amount with the same literal value.

## Expected Artifacts

```text
source_number_allowlist.json
prompt_attempt_0.md
agent_response_attempt_0.txt
validation_report_attempt_0.json
task_result.json
```

## Failure Scenarios

If the agent says satisfaction dropped to `95 percent`, the custom validator
rejects the invented number.

If a source label is missing, `ContainsPhrase` rejects the output.

If the agent invents an internal-looking issue ID, `ForbiddenPattern` rejects
the output.

## Stronger Future Shape

A stronger version should make `findings` a list of claim objects:

```json
{
  "findings": [
    {
      "claim": "Fulfillment time increased from 2.1 days to 3.4 days.",
      "citations": ["logistics-q3"],
      "numbers_used": ["2.1", "3.4"]
    }
  ]
}
```

That structure gives future semantic citation verification a clean upgrade path
without changing the outer workflow pattern.

## Bigger Picture

Source-derived validation is a practical middle ground between blind trust and a
full proof system. It catches common failures, gives reviewers concrete
artifacts, and creates a path toward deeper citation verification later.

## Ask Your Agent

This example is reference material for a coding agent to draft your own
citation-constrained workflow. Point the agent here and describe your use case:

> See `examples/focused_examples/02_citation_constrained_summary/example.py` as
> reference. Write me an Accentor file that takes quarterly financial data from
> two internal reports, has an agent draft an executive summary with findings,
> and validates that every numeric claim in the output actually appears in the
> source material. Require source labels on every finding and reject invented
> figures.

Other prompts that use this pattern:

- "Draft an Accentor file for our research lab: the agent summarizes
  experimental results from two datasets, and a custom validator rejects any
  measurement values that don't appear in the original instrument output."
- "Generate an Accentor file for a journalism fact-check pipeline: the agent
  drafts a summary from court filings, and validators ensure every dollar
  amount and date traces back to a cited document."

## API Pressure

This example forces stable answers for:

- custom validator authoring ergonomics
- whether validators inspect raw text, extracted JSON, or both
- whether common checks like allowed numeric literals deserve package helpers
