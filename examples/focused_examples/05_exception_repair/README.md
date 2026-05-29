# Exception Repair

**What this demonstrates:** Conventional code owns the happy path; an agent
repairs only after a declared failure, with scoped file access.
**Run:** `python example.py` (uses `CodexCli` — live provider)
**Expected output shape:**
```json
{"paid_order_count": 2, "paid_order_ids": ["1001", "1003"], "paid_total_amount": 63.99}
```
**What to inspect afterward:** `incident.json`, `proposed_diff.patch`,
`validation_report.json`, `output/paid_orders_summary.json`
**Tutorial prerequisite:** [08 Scoped Repair](../../tutorial/08_scoped_repair/)
---

## Purpose And Boundary

The pipeline is ordinary Python first. The agent is invoked only after a
declared deterministic failure occurs in `parse_orders`.

In this example, the code uses the wrong CSV delimiter. The expected columns are
missing, so the stage raises `ValueError`. Accentor can package the incident,
stage a repair workspace, ask an agent for a scoped patch, rerun the workflow,
and validate the result.

## Toy Flow

1. `parse_orders(DATA_FILE)` opens `data/orders.csv`.
2. `CSV_DELIMITER = "."` makes `csv.DictReader` parse the header incorrectly.
3. Missing expected columns trigger a `ValueError`.
4. The `on_error` policy activates only for `ValueError`.
5. The repair agent may read `example.py` and `data/orders.csv`, but may edit
   only `example.py`.
6. The workflow reruns and must produce `output/paid_orders_summary.json` with
   required keys.

## Parameters To Try

`EXPECTED_COLUMNS` defines the parser's contract with the CSV fixture. Adding a
column such as `currency` would make the parser stricter and could trigger the
same repair path for a different reason.

`CSV_DELIMITER` is intentionally wrong. Setting it to `","` should make the
happy path succeed without invoking agent repair.

The `on_error` key controls which exception types activate repair. If
`parse_orders` raised `FileNotFoundError`, this policy would not run unless that
exception were declared.

`readable=[Path(__file__), DATA_FILE]` gives the repair agent enough context to
diagnose the bug. `editable=[Path(__file__)]` prevents data mutation and keeps
the repair scope reviewable.

`CodexCli(sandbox="workspace-write")` is needed for a patching agent. A read-only
agent could diagnose the issue but could not apply a repair.

The validators currently check file presence and required keys. A stronger
version should also validate exact values, numeric precision, and row order.

## Internal Data Shapes

For `data/orders.csv`, the accepted summary is:

```json
{
  "paid_order_count": 2,
  "paid_order_ids": ["1001", "1003"],
  "paid_total_amount": 63.99
}
```

The incident record should include the failure and scope:

```json
{
  "stage": "parse_orders",
  "exception_type": "ValueError",
  "message": "CSV columns missing: ['amount', 'order_id', 'status']; parsed=['order_id,amount,status']; delimiter='.'",
  "readable": ["example.py", "data/orders.csv"],
  "editable": ["example.py"],
  "goal": "Repair CSV parsing so paid_orders_pipeline completes."
}
```

The declared repair policy is conceptually:

```json
{
  "trigger": "ValueError",
  "response": "agent_repair",
  "agent": {"provider": "CodexCli", "sandbox": "workspace-write"},
  "validators": [
    "RequiredFile(output/paid_orders_summary.json)",
    "RequiredKeys(paid_order_count, paid_order_ids, paid_total_amount)"
  ]
}
```

Example diff-scope verdict:

```json
{
  "ok": true,
  "edited_files": ["example.py"],
  "rejected_files": []
}
```

## Behavior In Other Settings

For ETL jobs, repair might be limited to parser configuration while data files
remain read-only. For generated code, repair might target a temporary workspace
and require human promotion before touching the project. For production
pipelines, repair could be disabled entirely but the same incident artifact
could open a ticket with enough context for a developer.

If the error is caused by bad data rather than bad code, the recovery policy
should be different. That might mean quarantine rows, request a corrected input
file, or generate a data-quality report instead of editing source code.

## Expected Artifacts

```text
incident.json
repair_prompt.md
proposed_diff.patch
diff_scope_verdict.json
rerun_stdout.txt
rerun_stderr.txt
validation_report.json
task_result.json
```

## Failure Scenarios

If the agent edits `data/orders.csv`, the diff-scope check should reject the
repair because only `example.py` is editable.

If the repaired code writes the wrong total, post-rerun validation should reject
the workflow.

If the original failure is not a `ValueError`, the declared repair policy should
not activate.

## Bigger Picture

Exception repair is a controlled handoff from deterministic code to an agent.
The value is not that the agent can patch a bug; it is that the system can state
when repair is allowed, what context is visible, what files may change, how the
rerun is validated, and what artifact gets promoted.

## Ask Your Agent

This example is reference material for a coding agent to draft your own
exception-repair workflow. Point the agent here and describe your use case:

> See `examples/focused_examples/05_exception_repair/example.py` as reference.
> Write me an Accentor file for our customer data import pipeline: the
> deterministic path parses a vendor CSV, validates required columns, computes
> summary metrics, and writes an audit artifact. When the parser fails because
> a new vendor uses different column names or delimiters, open an agentic
> repair boundary — the agent can edit only the parser file, the pipeline
> reruns, and exact output validators decide acceptance.

Other prompts that use this pattern:

- "Draft an Accentor file for our lab data pipeline: the normal path reads
  instrument output and produces a normalization report. When the instrument
  format changes, an agent repairs the parser under scoped file access and
  the pipeline reruns with row-count and schema validators."
- "Generate an Accentor file for our build system: when a generated config
  file fails validation, an agent proposes a scoped repair and the
  deterministic build reruns to decide acceptance."

## API Pressure

This example forces stable answers for:

- whether `on_error` remains dict-based or becomes typed recovery policy
- how rerun scope is defined
- how patch artifacts are represented
- how accepted repair output is promoted from staged workspace to project state
