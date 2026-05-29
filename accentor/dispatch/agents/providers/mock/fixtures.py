from __future__ import annotations

"""Reusable deterministic fixtures and contract checks for agent adapters."""

import json
import math
from collections.abc import Mapping
from typing import Any

from accentor.dispatch.agents.base import AgentCapabilities, AgentRequest, AgentRunResult
from accentor.dispatch.agents.providers.mock.adapter import ScriptedFailure


CONTRACT_PROMPT = "Return a short deterministic response for adapter contract tests."

VALID_JSON_OBJECT = {
    "title": "CSV Import Blank Plan Names",
    "summary": "Blank plan names create customer impact during onboarding.",
    "risks": ["Repeated upload retries", "Support escalation volume"],
    "next_steps": [
        "Improve validation copy",
        "Document required fields",
        "Track missing plan names",
    ],
}
VALID_JSON_RESPONSE = json.dumps(VALID_JSON_OBJECT, indent=2, sort_keys=True)
INVALID_JSON_RESPONSE = "not json"

BASIC_CAPABILITIES = AgentCapabilities(supports_tool_receipts=True)
BASIC_RECEIPT = {
    "kind": "tool_receipt",
    "provider": "mock",
    "tool": "mock.dispatch",
    "status": "ok",
    "elapsed_seconds": 0.0,
    "metadata": {"fixture": "basic_receipt"},
}
FAILURE_DIAGNOSTIC = {
    "code": "mock.scripted_failure",
    "message": "Scripted mock agent failure.",
    "severity": "error",
    "source": "mock_agent",
    "hint": None,
    "details": {},
}


def basic_receipt(
    *,
    status: str = "ok",
    tool: str = "mock.dispatch",
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    receipt = dict(BASIC_RECEIPT)
    receipt["status"] = status
    receipt["tool"] = tool
    receipt["metadata"] = {"fixture": "basic_receipt", **dict(metadata or {})}
    return receipt


def basic_capabilities(
    *,
    files: bool = False,
    shell: bool = False,
    sandbox: bool = False,
    persistence: bool = False,
    resume: bool = False,
    streaming: bool = False,
    tool_receipts: bool = False,
) -> AgentCapabilities:
    return AgentCapabilities(
        supports_files=files,
        supports_shell=shell,
        supports_sandbox=sandbox,
        supports_persistence=persistence,
        supports_resume=resume,
        supports_streaming=streaming,
        supports_tool_receipts=tool_receipts,
    )


def failure_result(
    *,
    message: str = "Scripted mock agent failure.",
    code: str = "mock.scripted_failure",
    exit_code: int | None = 1,
    output: str = "",
    capabilities: AgentCapabilities | Mapping[str, Any] | object | None = None,
    receipts: list[Any] | tuple[Any, ...] | None = None,
) -> AgentRunResult:
    diagnostic = {
        **FAILURE_DIAGNOSTIC,
        "code": code,
        "message": message,
    }
    return AgentRunResult(
        ok=False,
        output=output,
        elapsed_seconds=0.0,
        exit_code=exit_code,
        diagnostics=[diagnostic],
        receipts=list(receipts or ()),
        capabilities=capabilities or BASIC_CAPABILITIES,
        metadata={"adapter": "mock", "fixture": "failure_result"},
    )


def scripted_failure(
    *,
    message: str = "Scripted mock agent failure.",
    code: str = "mock.scripted_failure",
    output: str = "",
    exit_code: int | None = 1,
) -> ScriptedFailure:
    return ScriptedFailure(
        message=message,
        code=code,
        output=output,
        exit_code=exit_code,
        metadata={"fixture": "scripted_failure"},
    )


def contract_request() -> AgentRequest:
    return AgentRequest(prompt=CONTRACT_PROMPT, metadata={"fixture": "contract_request"})


def assert_json_stable(payload: Any) -> Any:
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    decoded = json.loads(encoded)
    assert json.dumps(decoded, allow_nan=False, sort_keys=True) == encoded
    return decoded


def assert_agent_adapter_contract(
    adapter: object,
    *,
    request: AgentRequest | None = None,
    expected_ok: bool | None = True,
) -> AgentRunResult:
    assert isinstance(getattr(adapter, "name", None), str)
    assert isinstance(getattr(adapter, "capabilities", None), AgentCapabilities)
    assert callable(getattr(adapter, "run", None))
    assert callable(getattr(adapter, "close", None))

    result = adapter.run(request or contract_request())
    assert_agent_run_result_contract(
        result,
        expected_ok=expected_ok,
        expected_capabilities=adapter.capabilities,
    )
    return result


def assert_agent_run_result_contract(
    result: object,
    *,
    expected_ok: bool | None = None,
    expected_capabilities: AgentCapabilities | Mapping[str, Any] | object | None = None,
) -> AgentRunResult:
    assert isinstance(result, AgentRunResult)
    if expected_ok is not None:
        assert result.ok is expected_ok
    assert isinstance(result.ok, bool)
    assert isinstance(result.output, str)
    assert result.final_message == result.output
    assert _is_finite_number(result.elapsed_seconds)
    assert result.elapsed_seconds >= 0.0
    assert result.wall_time_seconds == result.elapsed_seconds
    assert isinstance(result.diagnostics, list)
    assert result.exit_status == result.exit_code
    assert result.exit_code is None or isinstance(result.exit_code, int)
    assert isinstance(result.artifacts, list)
    assert isinstance(result.receipts, list)
    assert isinstance(result.metadata, dict)
    assert result.capabilities is None or isinstance(result.capabilities, AgentCapabilities)

    if expected_capabilities is not None:
        expected_snapshot = AgentCapabilities.from_any(expected_capabilities)
        assert result.capabilities == expected_snapshot
        if isinstance(expected_capabilities, AgentCapabilities):
            assert result.capabilities is not expected_capabilities

    payload = assert_json_stable(result.to_dict())
    assert payload["output"] == payload["final_message"]
    assert payload["elapsed_seconds"] == payload["wall_time_seconds"]
    assert payload["exit_code"] == payload["exit_status"]
    return result


def assert_agent_failure_contract(
    result: object,
    *,
    expected_code: str | None = None,
    expected_capabilities: AgentCapabilities | Mapping[str, Any] | object | None = None,
) -> AgentRunResult:
    checked = assert_agent_run_result_contract(
        result,
        expected_ok=False,
        expected_capabilities=expected_capabilities,
    )
    assert checked.diagnostics
    if expected_code is not None:
        assert any(_diagnostic_code(diagnostic) == expected_code for diagnostic in checked.diagnostics)
    return checked


def _diagnostic_code(diagnostic: Any) -> str | None:
    if isinstance(diagnostic, Mapping):
        code = diagnostic.get("code")
    else:
        code = getattr(diagnostic, "code", None)
    return str(code) if code is not None else None


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


__all__ = [
    "BASIC_CAPABILITIES",
    "BASIC_RECEIPT",
    "CONTRACT_PROMPT",
    "FAILURE_DIAGNOSTIC",
    "INVALID_JSON_RESPONSE",
    "VALID_JSON_OBJECT",
    "VALID_JSON_RESPONSE",
    "assert_agent_adapter_contract",
    "assert_agent_failure_contract",
    "assert_agent_run_result_contract",
    "assert_json_stable",
    "basic_capabilities",
    "basic_receipt",
    "contract_request",
    "failure_result",
    "scripted_failure",
]
