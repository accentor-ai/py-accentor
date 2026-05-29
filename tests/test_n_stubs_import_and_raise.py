from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from accentor.dispatch.agents.base import AgentRequest
from accentor.dispatch.routing.base import RoutingContext
from accentor.dispatch.workspace import WorkspacePlan


def test_named_non_provider_stubs_import_and_raise_on_behavior() -> None:
    from accentor.core.composition.mapping import map_over
    from accentor.core.composition.parallel import parallel
    from accentor.core.task.mutations import TaskMutation
    from accentor.dispatch.agents.manifest import AdapterManifest
    from accentor.dispatch.routing.adapters import ClassifierRouter
    from accentor.dispatch.routing.tables import RoutingTable
    from accentor.dispatch.workspace.docker import DockerWorkspaceBackend
    from accentor.dispatch.workspace.remote import RemoteWorkspaceBackend
    from accentor.record.artifacts.object_store import ObjectStoreBackend
    from accentor.record.observe.langsmith import LangSmithSink
    from accentor.record.observe.opentelemetry import OtelSink
    from accentor.record.observe.sqlite import SqliteSink

    routing_context = RoutingContext(stage="route", input={})
    workspace_plan = WorkspacePlan.empty()

    behaviors = [
        lambda: parallel(lambda: "x"),
        lambda: map_over(lambda item: item, [1]),
        lambda: TaskMutation().apply(object()),
        lambda: AdapterManifest().discover(),
        lambda: ClassifierRouter().route(routing_context),
        lambda: RoutingTable.from_file("routes.yaml"),
        lambda: RoutingTable().route(routing_context),
        lambda: DockerWorkspaceBackend().prepare(workspace_plan),
        lambda: RemoteWorkspaceBackend().prepare(workspace_plan),
        lambda: SqliteSink().emit({"event_type": "x"}),
        lambda: OtelSink().emit({"event_type": "x"}),
        lambda: LangSmithSink().emit({"event_type": "x"}),
        lambda: ObjectStoreBackend().put("artifact.txt", "data"),
    ]

    for behavior in behaviors:
        with pytest.raises(NotImplementedError):
            behavior()


def test_existing_validator_stubs_return_structured_unsupported_diagnostic() -> None:
    from accentor.evaluate.validation.code import RuffValidator
    from accentor.evaluate.validation.pydantic import PydanticValidator
    from accentor.evaluate.validation.tabular import PandasValidator

    for validator in (RuffValidator(), PydanticValidator(), PandasValidator()):
        result = validator.validate("candidate")
        assert result.ok is False
        assert result.diagnostics[0].code == "validation.unsupported"
        assert result.diagnostics[0].details["feature"] == validator.feature


def test_stub_modules_do_not_import_optional_dependencies_at_import_time() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    modules = [
        "accentor.dispatch.agents.manifest",
        "accentor.dispatch.routing.adapters",
        "accentor.dispatch.routing.tables",
        "accentor.dispatch.workspace.docker",
        "accentor.dispatch.workspace.remote",
        "accentor.record.observe.sqlite",
        "accentor.record.observe.opentelemetry",
        "accentor.record.observe.langsmith",
        "accentor.record.artifacts.object_store",
    ]
    code = f"""
import importlib
import json
import sys

for module in {modules!r}:
    importlib.import_module(module)

blocked = [
    name for name in sorted(sys.modules)
    if name.startswith("langchain")
    or name.startswith("anthropic")
    or name.startswith("google.generativeai")
    or name.startswith("docker")
    or name.startswith("opentelemetry")
    or name.startswith("langsmith")
    or name.startswith("pydantic")
    or name.startswith("pandas")
]
print(json.dumps(blocked))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == []


def test_all_proposed_stub_modules_are_directly_importable() -> None:
    modules = [
        "accentor.dispatch.agents.manifest",
        "accentor.dispatch.routing.adapters",
        "accentor.dispatch.routing.tables",
        "accentor.dispatch.workspace.docker",
        "accentor.dispatch.workspace.remote",
        "accentor.core.task.mutations",
        "accentor.core.composition.parallel",
        "accentor.core.composition.mapping",
        "accentor.record.observe.sqlite",
        "accentor.record.observe.opentelemetry",
        "accentor.record.observe.langsmith",
        "accentor.record.artifacts.object_store",
    ]

    for module in modules:
        assert importlib.import_module(module)
