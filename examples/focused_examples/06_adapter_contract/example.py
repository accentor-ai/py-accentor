"""Focused example: offline adapter contract check plus optional live smoke.

General purpose:
    Show that providers should be swappable behind one adapter contract. The
    workflow layer can rely on AgentRunResult only if every adapter returns the
    same basic fields and failure shape.

Toy setting:
    MockAgent is checked offline for CI-friendly contract coverage. Passing
    --live additionally runs the same request through CodexCli as a real
    provider smoke test.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from accentor.dispatch.agents.base import AgentAdapter, AgentRequest, AgentRunResult
from accentor.dispatch.agents.providers.mock import MockAgent


REQUEST = AgentRequest(
    prompt="Describe one common reason CSV imports fail. Answer in one sentence.",
)

MOCK_RESPONSE = (
    "CSV imports often fail because the file contains a header row that does "
    "not match the expected column names."
)


def check_contract(label: str, result: AgentRunResult) -> list[str]:
    # This intentionally checks the minimum fields higher-level Accentor code
    # needs to make routing, validation, diagnostics, and timing observable.
    errors: list[str] = []
    try:
        if not isinstance(result.output, str):
            errors.append(f"[{label}] output is not a string: {type(result.output)}")
    except AttributeError:
        errors.append(f"[{label}] missing field: output")
    try:
        if not isinstance(result.ok, bool):
            errors.append(f"[{label}] ok is not a bool: {type(result.ok)}")
    except AttributeError:
        errors.append(f"[{label}] missing field: ok")
    try:
        if not isinstance(result.elapsed_seconds, (int, float)):
            errors.append(
                f"[{label}] elapsed_seconds is not numeric: "
                f"{type(result.elapsed_seconds)}"
            )
    except AttributeError:
        errors.append(f"[{label}] missing field: elapsed_seconds")
    try:
        if not isinstance(result.diagnostics, list):
            errors.append(
                f"[{label}] diagnostics is not a list: {type(result.diagnostics)}"
            )
    except AttributeError:
        errors.append(f"[{label}] missing field: diagnostics")
    return errors


def run_adapter(label: str, adapter: AgentAdapter) -> AgentRunResult:
    # The same AgentRequest is sent to each adapter. That keeps provider
    # behavior separate from the contract check itself.
    print(f"--- {label} ---")
    result = adapter.run(REQUEST)
    print(f"  ok:      {result.ok}")
    print(f"  output:  {result.output[:80]}...")
    print(f"  elapsed: {result.elapsed_seconds:.2f}s")
    print(f"  diags:   {len(result.diagnostics)} diagnostic(s)")
    return result


if __name__ == "__main__":
    all_errors: list[str] = []

    # The mock path should be deterministic and safe to run in ordinary tests.
    mock = MockAgent(responses=[MOCK_RESPONSE])
    mock_result = run_adapter("MockAgent", mock)
    all_errors.extend(check_contract("MockAgent", mock_result))

    if "--live" in sys.argv:
        # Live smoke tests are opt-in because they depend on local credentials,
        # provider availability, and CLI behavior outside the package.
        from accentor.dispatch.agents.providers.codex_cli import CodexCli

        codex = CodexCli(sandbox="read-only")
        codex_result = run_adapter("CodexCli", codex)
        all_errors.extend(check_contract("CodexCli", codex_result))
    else:
        print("\n(Skipping CodexCli - pass --live for real provider smoke test)")

    if all_errors:
        print("\nContract violations:")
        for error in all_errors:
            print(f"  - {error}")
    else:
        print("\nAll tested adapters satisfy the AgentRunResult contract.")

    # Bigger picture: adapter conformance tests protect the rest of Accentor
    # from provider-specific surprises when workflows change providers.
