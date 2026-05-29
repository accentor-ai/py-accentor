from __future__ import annotations

"""Mock agent provider for deterministic tests."""

from accentor.dispatch.agents.providers.mock import fixtures as fixtures
from accentor.dispatch.agents.providers.mock.adapter import (
    MockAgent,
    MockAgentFailure,
    MockResponse,
    ResponseLike,
    ScriptedFailure,
    mock_failure,
)
from accentor.dispatch.agents.providers.mock.fixtures import (
    BASIC_CAPABILITIES,
    BASIC_RECEIPT,
    CONTRACT_PROMPT,
    FAILURE_DIAGNOSTIC,
    INVALID_JSON_RESPONSE,
    VALID_JSON_OBJECT,
    VALID_JSON_RESPONSE,
    assert_agent_adapter_contract,
    assert_agent_failure_contract,
    assert_agent_run_result_contract,
    assert_json_stable,
    basic_capabilities,
    basic_receipt,
    contract_request,
    failure_result,
    scripted_failure,
)

__all__ = [
    "BASIC_CAPABILITIES",
    "BASIC_RECEIPT",
    "CONTRACT_PROMPT",
    "FAILURE_DIAGNOSTIC",
    "INVALID_JSON_RESPONSE",
    "MockAgent",
    "MockAgentFailure",
    "MockResponse",
    "ResponseLike",
    "ScriptedFailure",
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
    "fixtures",
    "mock_failure",
    "scripted_failure",
]
