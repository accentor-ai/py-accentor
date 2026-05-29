from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path


def test_base_contracts_import_from_all_public_dispatch_surfaces() -> None:
    from accentor.dispatch import AgentAdapter as DispatchAgentAdapter
    from accentor.dispatch import AgentCapabilities as DispatchAgentCapabilities
    from accentor.dispatch import AgentRequest as DispatchAgentRequest
    from accentor.dispatch import AgentRunResult as DispatchAgentRunResult
    from accentor.dispatch.agents import AgentAdapter as AgentsAgentAdapter
    from accentor.dispatch.agents.base import (
        AgentAdapter,
        AgentCapabilities,
        AgentRequest,
        AgentRunResult,
    )

    assert DispatchAgentAdapter is AgentAdapter
    assert AgentsAgentAdapter is AgentAdapter
    assert DispatchAgentCapabilities is AgentCapabilities
    assert DispatchAgentRequest is AgentRequest
    assert DispatchAgentRunResult is AgentRunResult


def test_agent_result_aliases_and_capability_snapshot() -> None:
    from accentor.dispatch.agents.base import AgentCapabilities, AgentRunResult

    capabilities = AgentCapabilities(files=True, persistent_sessions=True)
    result = AgentRunResult(output="done", elapsed_seconds=1.25, capabilities=capabilities)

    assert result.final_message == "done"
    assert result.wall_time_seconds == 1.25
    assert result.capabilities == capabilities
    assert result.capabilities is not capabilities
    assert result.capabilities.files is True
    assert result.capabilities.persistent_sessions is True


def test_agent_request_redacted_serialization_does_not_mutate_original() -> None:
    from accentor.dispatch.agents.base import AgentRequest

    request = AgentRequest(
        prompt="secret prompt",
        messages=[{"role": "user", "content": "secret message"}],
        provider_options={"api_key": "secret-key", "safe": "visible"},
    )

    redacted = request.redacted()

    assert request.prompt == "secret prompt"
    assert request.messages[0]["content"] == "secret message"
    encoded = json.dumps(redacted, sort_keys=True)
    assert "secret prompt" not in encoded
    assert "secret message" not in encoded
    assert "secret-key" not in encoded
    assert redacted["provider_options"]["safe"] == "visible"


def test_persistent_agent_adapter_stub_raises_for_run_behavior() -> None:
    import pytest

    from accentor.dispatch.agents.base import AgentRequest, PersistentAgentAdapter

    adapter = PersistentAgentAdapter()

    with pytest.raises(NotImplementedError, match="not supported in v1"):
        adapter.run(AgentRequest(prompt="hello"))


def test_importing_dispatch_contracts_does_not_import_provider_modules() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    code = """
import json
import sys

import accentor
from accentor.dispatch import AgentAdapter, AgentCapabilities, AgentRequest, AgentRunResult
from accentor.dispatch.agents import AgentAdapter as AgentsAgentAdapter
from accentor.dispatch.agents.base import AgentAdapter as BaseAgentAdapter

assert AgentAdapter is AgentsAgentAdapter is BaseAgentAdapter
assert AgentCapabilities
assert AgentRequest
assert AgentRunResult

print(json.dumps([
    name for name in sorted(sys.modules)
    if name == "accentor.dispatch.agents.providers"
    or name.startswith("accentor.dispatch.agents.providers.")
]))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == []


def test_provider_modules_remain_directly_importable() -> None:
    importlib.import_module("accentor.dispatch.agents.providers.mock.adapter")
    importlib.import_module("accentor.dispatch.agents.providers.codex_cli.adapter")
