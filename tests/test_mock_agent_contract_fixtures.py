from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from accentor.dispatch.agents.base import AgentCapabilities, AgentRequest, AgentRunResult
from accentor.dispatch.agents.providers.mock import MockAgent
from accentor.dispatch.agents.providers.mock.fixtures import (
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


def test_mock_fixture_payloads_are_deterministic_and_json_stable() -> None:
    assert json.loads(VALID_JSON_RESPONSE) == VALID_JSON_OBJECT
    with pytest.raises(json.JSONDecodeError):
        json.loads(INVALID_JSON_RESPONSE)

    receipt = assert_json_stable(basic_receipt(metadata={"attempt": 0}))
    capabilities = assert_json_stable(basic_capabilities(tool_receipts=True).to_dict())
    result = assert_agent_failure_contract(failure_result())

    assert receipt["provider"] == "mock"
    assert capabilities["supports_tool_receipts"] is True
    assert result.diagnostics[0]["code"] == "mock.scripted_failure"


def test_mock_agent_satisfies_reusable_adapter_contract_for_valid_json() -> None:
    adapter = MockAgent(responses=[VALID_JSON_RESPONSE])

    result = assert_agent_adapter_contract(adapter, request=contract_request())

    assert result.output == VALID_JSON_RESPONSE
    assert json.loads(result.final_message) == VALID_JSON_OBJECT
    assert result.wall_time_seconds == result.elapsed_seconds
    assert result.capabilities == adapter.capabilities
    assert result.capabilities is not adapter.capabilities
    assert adapter.run_count == 1
    assert adapter.remaining_responses == 0


def test_mock_agent_returns_invalid_json_as_plain_success_output() -> None:
    adapter = MockAgent(responses=[INVALID_JSON_RESPONSE])

    result = assert_agent_adapter_contract(adapter, request=AgentRequest(prompt="json please"))

    assert result.ok is True
    assert result.output == INVALID_JSON_RESPONSE
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.output)


def test_mock_agent_reports_exhausted_responses_as_structured_failure() -> None:
    adapter = MockAgent(responses=[])

    result = adapter.run(AgentRequest(prompt="one more"))

    assert_agent_failure_contract(
        result,
        expected_code="mock.responses_exhausted",
        expected_capabilities=adapter.capabilities,
    )
    assert result.output == ""
    assert result.exit_code == 1


def test_mock_agent_accepts_scripted_failure_and_result_fixtures() -> None:
    capabilities = basic_capabilities(persistence=True, tool_receipts=True)
    receipt = basic_receipt(status="error")
    adapter = MockAgent(
        responses=[
            scripted_failure(code="mock.fixture_failure", output="partial output"),
            failure_result(code="mock.prebuilt_failure", receipts=[receipt]),
        ],
        capabilities=capabilities,
        receipts=[receipt],
        session="persistent",
    )

    first = adapter.run(AgentRequest(prompt="fail once"))
    second = adapter.run(AgentRequest(prompt="fail twice"))

    assert_agent_failure_contract(first, expected_code="mock.fixture_failure")
    assert_agent_failure_contract(second, expected_code="mock.prebuilt_failure")
    assert first.output == "partial output"
    assert first.capabilities.persistent_sessions is True
    assert first.receipts == [receipt]
    assert second.receipts == [receipt, receipt]


def test_contract_helper_checks_direct_run_results_for_future_provider_smokes() -> None:
    capabilities = AgentCapabilities(files=True, sandbox=True)
    result = AgentRunResult(
        output="done",
        elapsed_seconds=0.25,
        capabilities=capabilities,
        receipts=[basic_receipt()],
    )

    checked = assert_agent_run_result_contract(
        result,
        expected_ok=True,
        expected_capabilities=capabilities,
    )

    assert checked.final_message == "done"
    assert checked.capabilities is not capabilities


def test_mock_agent_adapter_contract() -> None:
    assert_agent_adapter_contract(MockAgent(responses=["{}"]))
    adapter = MockAgent(responses=["{}"])
    result = adapter.run(AgentRequest(prompt="health"))
    assert isinstance(adapter, MockAgent)
    assert result.output == "{}"
