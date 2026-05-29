from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from accentor import (
    DispatchPlan,
    PermissionIntent,
    Task,
    TaskResult,
    ValidationResult,
    Validator,
    WorkspaceIntent,
    stage,
    workflow,
)
from accentor.dispatch.agents.providers.mock import MockAgent


def test_root_public_api_matches_proposed_v1_surface() -> None:
    assert Task
    assert TaskResult
    assert workflow
    assert stage
    assert PermissionIntent
    assert WorkspaceIntent
    assert DispatchPlan
    assert Validator
    assert ValidationResult


def test_package_level_public_exports_resolve_without_provider_imports() -> None:
    from accentor.core import Step, TaskEvent, retry, sequence
    from accentor.evaluate import JsonExtractor, JsonRequired
    from accentor.record import ArtifactStore, JsonlSink, TaskObserver

    assert Step
    assert TaskEvent
    assert retry
    assert sequence
    assert JsonExtractor
    assert JsonRequired
    assert ArtifactStore
    assert JsonlSink
    assert TaskObserver

    repo_root = Path(__file__).resolve().parents[1]
    code = """
import json
import sys

from accentor.core import Step, TaskEvent, retry, sequence
from accentor.evaluate import JsonExtractor, JsonRequired
from accentor.record import ArtifactStore, JsonlSink, TaskObserver

assert Step and TaskEvent and retry and sequence
assert JsonExtractor and JsonRequired
assert ArtifactStore and JsonlSink and TaskObserver
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


def test_dispatch_plan_request_shape_is_consumed_by_mock_agent() -> None:
    agent = MockAgent(responses=["accepted"])
    plan = DispatchPlan(
        stage="prompt_only",
        agent=agent,
        prompt="Return accepted.",
        provider_options={"temperature": 0},
    )

    result = agent.run(plan.to_agent_request())

    assert result.ok is True
    assert result.output == "accepted"
    assert agent.requests[0].prompt == "Return accepted."
    assert agent.requests[0].permissions["sandbox_mode"] == "none"
    assert agent.requests[0].workspace is None


def test_prompt_only_agent_stage_uses_agent_request_without_workspace(tmp_path) -> None:
    agent = MockAgent(responses=["stage output"])

    @stage(agent=agent, provider_options={"temperature": 0})
    def draft() -> str:
        return "Draft a short response."

    result = draft(artifact_root=tmp_path)

    assert result.ok is True
    assert result.output == "stage output"
    assert agent.requests
    assert agent.requests[0].prompt == "Draft a short response."
    assert agent.requests[0].workspace is None
    assert agent.requests[0].permissions == {}
    assert agent.requests[0].provider_options["temperature"] == 0


def test_root_import_does_not_import_provider_modules() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    code = """
import json
import sys

from accentor import (
    DispatchPlan,
    PermissionIntent,
    Task,
    TaskResult,
    ValidationResult,
    Validator,
    WorkspaceIntent,
    stage,
    workflow,
)

assert Task
assert TaskResult
assert workflow
assert stage
assert PermissionIntent
assert WorkspaceIntent
assert DispatchPlan
assert Validator
assert ValidationResult
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
