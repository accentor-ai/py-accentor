from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from accentor.configure import DispatchPlan, PermissionIntent, SandboxMode, WorkspaceIntent
from accentor.dispatch.agents.base import AgentRequest
from accentor.dispatch.agents.providers.mock import MockAgent
from accentor.evaluate.validation import ContainsPhrase


def assert_json_stable(payload: dict) -> dict:
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    return json.loads(encoded)


def test_prompt_only_dispatch_plan_builds_agent_request_without_workspace() -> None:
    provider_options = {"temperature": 0, "api_key": "secret"}
    plan = DispatchPlan(
        stage="summarize",
        agent="mock",
        prompt="Summarize this.",
        call_args={"topic": "shipping", "ctx": object()},
        provider_options=provider_options,
        metadata={"purpose": "test"},
    )
    provider_options["temperature"] = 1

    request = plan.to_agent_request()

    assert isinstance(request, AgentRequest)
    assert request.prompt == "Summarize this."
    assert request.workspace is None
    assert request.permissions["sandbox_mode"] == "none"
    assert request.metadata["call_args"] == {"topic": "shipping"}
    assert request.provider_options["temperature"] == 0
    assert_json_stable(plan.to_dict())
    assert_json_stable(request.to_dict())


def test_read_only_and_workspace_write_modes_come_from_compiled_scope(tmp_path) -> None:
    source = tmp_path / "inputs" / "guide.txt"
    editable = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    editable.parent.mkdir()
    source.write_text("guide", encoding="utf-8")
    editable.write_text("old", encoding="utf-8")

    read_permissions = PermissionIntent(root=tmp_path, readable=[source]).compile()
    read_workspace = WorkspaceIntent(root=tmp_path, readable=[source]).compile()
    read_plan = DispatchPlan(
        stage="read",
        prompt="Read only",
        workspace=read_workspace,
        permissions=read_permissions,
    )

    write_permissions = PermissionIntent(root=tmp_path, editable=[editable]).compile()
    write_workspace = WorkspaceIntent(root=tmp_path, editable=[editable], outputs=["src/app.py"]).compile()
    write_plan = DispatchPlan(
        stage="repair",
        prompt="Repair",
        workspace=write_workspace,
        permissions=write_permissions,
    )

    assert read_plan.sandbox_mode is SandboxMode.READ_ONLY
    assert read_plan.to_agent_request().permissions["sandbox_mode"] == "read_only"
    assert write_plan.sandbox_mode is SandboxMode.WORKSPACE_WRITE
    request = write_plan.to_agent_request()
    assert request.permissions["sandbox_mode"] == "workspace_write"
    assert request.metadata["workspace"]["editable"] == ["src/app.py"]
    assert "diff_scope" in request.permissions["post_run_checks"]
    assert_json_stable(request.to_dict())


def test_dispatch_plan_preserves_routing_validator_timeout_and_redacts_sensitive_values() -> None:
    plan = DispatchPlan(
        stage="draft",
        agent=MockAgent(responses=["ok"]),
        prompt="secret prompt",
        messages=[{"role": "user", "content": "secret message"}],
        routing={"selected": "legal"},
        validators=[ContainsPhrase("approved")],
        provider_options={"token": "secret-token", "safe": "visible"},
        timeout_seconds=3,
        metadata={"secret": "hidden", "safe": "shown"},
    )

    request = plan.to_agent_request()
    redacted_plan = plan.redacted()
    redacted_request = request.redacted()
    encoded = json.dumps({"plan": redacted_plan, "request": redacted_request}, sort_keys=True)

    assert request.timeout_seconds == 3
    assert request.metadata["routing"] == {"selected": "legal"}
    assert request.metadata["validators"][0]["name"] == "ContainsPhrase"
    assert "secret prompt" not in encoded
    assert "secret message" not in encoded
    assert "secret-token" not in encoded
    assert redacted_plan["provider_options"]["safe"] == "visible"
    assert redacted_plan["metadata"]["safe"] == "shown"


def test_to_agent_request_does_not_call_provider() -> None:
    agent = MockAgent(responses=["ok"])
    plan = DispatchPlan(stage="agent", agent=agent, prompt="hello")

    request = plan.to_agent_request()

    assert agent.run_count == 0
    assert agent.requests == []
    assert request.prompt == "hello"


def test_importing_configure_does_not_import_provider_modules() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    code = """
import json
import sys

from accentor.configure import DispatchPlan, PermissionIntent, WorkspaceIntent

assert DispatchPlan
assert PermissionIntent
assert WorkspaceIntent
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
