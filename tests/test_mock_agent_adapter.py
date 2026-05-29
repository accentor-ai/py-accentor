from __future__ import annotations

from pathlib import Path

import pytest

from accentor.dispatch.agents.base import AgentCapabilities, AgentRequest, AgentRunResult
from accentor.dispatch.agents.providers.mock import MockAgent, MockAgentFailure, mock_failure


def diagnostic_codes(result: AgentRunResult) -> list[str]:
    codes: list[str] = []
    for diagnostic in result.diagnostics:
        if isinstance(diagnostic, dict):
            codes.append(str(diagnostic.get("code")))
        else:
            codes.append(str(getattr(diagnostic, "code")))
    return codes


def test_mock_agent_consumes_responses_in_order_across_runs() -> None:
    adapter = MockAgent(responses=["first", "second"])
    request = AgentRequest(prompt="ignored by the deterministic mock")

    first = adapter.run(request)
    second = adapter.run(request)

    assert first.ok is True
    assert first.output == "first"
    assert first.metadata["response_index"] == 0
    assert second.ok is True
    assert second.output == "second"
    assert second.metadata["response_index"] == 1
    assert adapter.consumed_count == 2
    assert adapter.exhausted is True


def test_mock_agent_returns_structured_failure_when_responses_are_exhausted() -> None:
    adapter = MockAgent(responses=["only"])

    assert adapter.run(AgentRequest(prompt="first")).output == "only"
    exhausted = adapter.run(AgentRequest(prompt="second"))

    assert exhausted.ok is False
    assert exhausted.output == ""
    assert exhausted.exit_code == 1
    assert diagnostic_codes(exhausted) == ["mock.responses_exhausted"]
    assert exhausted.diagnostics[0]["details"]["response_count"] == 1
    assert exhausted.capabilities == adapter.capabilities
    assert exhausted.capabilities is not adapter.capabilities


def test_mock_agent_turns_scripted_failures_into_failed_results() -> None:
    adapter = MockAgent(
        responses=[
            MockAgentFailure(
                code="mock.timeout",
                message="Scripted timeout.",
                exit_code=124,
                metadata={"case": "timeout"},
            )
        ]
    )

    result = adapter.run(AgentRequest(prompt="please time out"))

    assert result.ok is False
    assert result.exit_code == 124
    assert diagnostic_codes(result) == ["mock.timeout"]
    assert result.diagnostics[0]["message"] == "Scripted timeout."
    assert result.metadata["scripted_failure"] is True
    assert result.metadata["case"] == "timeout"


def test_mock_failure_helper_builds_structured_failure_response() -> None:
    adapter = MockAgent(
        responses=[
            mock_failure(
                "Provider denied the request.",
                code="mock.denied",
                output="partial output",
            )
        ]
    )

    result = adapter.run(AgentRequest(prompt="deny this"))

    assert result.ok is False
    assert result.output == "partial output"
    assert diagnostic_codes(result) == ["mock.denied"]


def test_mock_agent_result_carries_capability_snapshot() -> None:
    capabilities = AgentCapabilities(files=True, sandbox=True)
    adapter = MockAgent(responses=["done"], capabilities=capabilities)

    result = adapter.run(AgentRequest(prompt="capability check"))

    assert result.capabilities == capabilities
    assert result.capabilities is not capabilities
    assert result.capabilities.files is True
    assert result.capabilities.sandbox is True


def test_persistent_session_marker_is_recorded_without_memory_simulation() -> None:
    adapter = MockAgent(responses=["alpha", "beta"], session="persistent")

    first = adapter.run(AgentRequest(prompt="Remember alpha."))
    second = adapter.run(AgentRequest(prompt="What did I ask you to remember?"))

    assert first.output == "alpha"
    assert second.output == "beta"
    assert first.metadata["session"] == "persistent"
    assert second.metadata["session"] == "persistent"
    assert first.capabilities.persistent_sessions is True
    assert second.capabilities.persistent_sessions is True


def test_mock_agent_rejects_unknown_session_mode() -> None:
    with pytest.raises(ValueError, match="session='persistent'"):
        MockAgent(responses=["ok"], session="other")


def test_mock_agent_result_aliases_are_available() -> None:
    result = MockAgent(responses=["alias output"]).run(AgentRequest(prompt="aliases"))

    assert result.output == "alias output"
    assert result.final_message == "alias output"
    assert result.elapsed_seconds == 0.0
    assert result.wall_time_seconds == 0.0
    assert result.exit_code == 0
    assert result.exit_status == 0
    payload = result.to_dict()
    assert payload["output"] == payload["final_message"] == "alias output"
    assert payload["elapsed_seconds"] == payload["wall_time_seconds"] == 0.0


def test_mock_agent_does_not_create_or_modify_files_from_text_response(tmp_path: Path) -> None:
    existing = tmp_path / "existing.txt"
    target = tmp_path / "created.txt"
    existing.write_text("original", encoding="utf-8")
    adapter = MockAgent(
        responses=[
            f"Create {target} and change existing.txt. This is only response text."
        ]
    )

    result = adapter.run(
        AgentRequest(
            prompt="Repair the workspace.",
            workspace={"root": tmp_path, "files": [existing]},
        )
    )

    assert result.ok is True
    assert result.output.startswith("Create ")
    assert existing.read_text(encoding="utf-8") == "original"
    assert not target.exists()
