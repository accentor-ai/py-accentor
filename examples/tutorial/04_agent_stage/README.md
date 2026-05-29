# 04 Agent Stage

**Primitive:** Agent-backed stages with `MockAgent`.

**What you learn:** How to use `MockAgent` in a stage, understand
`AgentRequest` shape, use `inject_criteria`, and optionally swap in a live
provider.

**Run:** `python example.py` (mock-only by default; `--live` for live provider)

## Key Concepts

An agent stage sends a request to a provider and validates the response. In
tutorials and CI, `MockAgent` provides deterministic responses. The same stage
definition works with any adapter that conforms to the `AgentRunResult`
contract.

## After This Module

- Next: [05 Extraction and Retry](../05_extraction_and_retry/)
- See agent stages in a real use case: [Focused Example 03 — PII-Filtered Draft](../../focused_examples/03_pii_filtered_draft/)
- See adapter conformance: [Focused Example 07 — Adapter Contract](../../focused_examples/06_adapter_contract/)
