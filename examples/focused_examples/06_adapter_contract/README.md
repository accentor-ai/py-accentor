# Adapter Contract

**What this demonstrates:** Provider adapters are swappable behind one runtime
contract. *(Developer-focused)*
**Run:** `python example.py` (mock-only by default; `python example.py --live`
for live provider smoke test)
**Expected output shape:**
```json
{"adapter": "MockAgent", "ok": true, "fields_checked": ["output", "ok", "elapsed_seconds", "diagnostics"], "violations": []}
```
**What to inspect afterward:** `mock_agent_result.json`,
`adapter_contract_report.json`

---

## Purpose And Boundary

This example exercises the adapter layer directly. It does not use
`workflow(...)` or `stage(...)` because the goal is provider conformance, not
workflow composition.

The offline path uses `MockAgent` and should be safe for CI. The live path uses
`CodexCli` only when `--live` is passed.

## Toy Flow

1. Build one `AgentRequest`.
2. Run that request through `MockAgent`.
3. Check that the returned object has the expected `AgentRunResult` fields.
4. Optionally run the same request through `CodexCli` with `--live`.
5. Print contract violations instead of hiding provider-specific failures.

## Parameters To Try

`REQUEST.prompt` can be changed to exercise different output lengths or
instruction-following behavior. The contract check should not depend on the
semantic quality of one specific answer.

`MockAgent(responses=[MOCK_RESPONSE])` makes CI deterministic. Additional mock
responses could simulate retries, failures, empty output, diagnostics, or
timeouts.

`--live` is intentionally opt-in. Live provider checks depend on local
credentials, installed CLIs, network/provider availability, and provider version.

`check_contract(...)` currently checks `output`, `ok`, `elapsed_seconds`, and
`diagnostics`. If the v0 API settles on `final_message`, `exit_code`,
`wall_time_seconds`, `capabilities`, or richer transcript fields, this example
should check those canonical names instead.

## Internal Data Shapes

The request is deliberately small:

```json
{
  "prompt": "Describe one common reason CSV imports fail. Answer in one sentence."
}
```

Expected contract report:

```json
{
  "adapter": "MockAgent",
  "ok": true,
  "fields_checked": ["output", "ok", "elapsed_seconds", "diagnostics"],
  "violations": []
}
```

Example failure-result shape:

```json
{
  "adapter": "MockAgent",
  "ok": false,
  "exit_code": 124,
  "diagnostics": [
    {
      "code": "adapter_timeout",
      "message": "Adapter exceeded the configured timeout."
    }
  ]
}
```

## Behavior In Other Settings

In package tests, the mock path should run on every commit. In pre-release
checks, live smoke tests can run against supported providers. In user projects,
the same contract check can help verify a custom adapter before it is trusted by
workflows.

If a provider lacks persistent sessions, workspace writes, or streaming output,
that should appear in an explicit capability snapshot before higher-level
examples depend on those features.

## Expected Artifacts

```text
mock_agent_result.json
adapter_contract_report.json
codex_cli_result.json        # only for --live
```

## Failure Scenarios

If a provider times out, the adapter should return a structured failed result
rather than raising an opaque exception.

If a provider exits non-zero, the result should preserve stdout, stderr, exit
code, diagnostics, and adapter identity.

If a provider returns an unexpected object shape, `check_contract(...)` should
report the missing or mistyped fields.

## Bigger Picture

Adapter conformance is what lets the rest of Accentor stay provider-neutral.
Workflows, validators, routing, and repair policies should not need special
branches for every CLI or model provider.

## Ask Your Agent

This example is reference material for a coding agent to draft adapter
conformance checks for your provider setup. Point the agent here and describe
your use case:

> See `examples/focused_examples/06_adapter_contract/example.py` as reference.
> Write me an Accentor adapter contract check for our project: we use CodexCli
> in production and MockAgent in CI. Generate a script that sends the same
> request to both, checks the response shape against the AgentRunResult
> contract, and prints a conformance report. Include a --live flag so CI only
> runs the mock path.

Other prompts that use this pattern:

- "Draft an Accentor adapter check that exercises persistent-session capability
  for our CodexCli setup, so we know session reuse works before we depend on
  it in a read-verification workflow."
- "Generate an Accentor adapter contract check that tests timeout and failure
  behavior: send a request that should fail, and verify the adapter returns a
  structured failed result with diagnostics instead of raising an exception."

## API Pressure

This example forces stable answers for:

- public `AgentRunResult` v0 field names
- whether convenience aliases like `output` and `elapsed_seconds` exist
- `AgentCapabilities` shape
- reusable adapter conformance fixtures for package tests
