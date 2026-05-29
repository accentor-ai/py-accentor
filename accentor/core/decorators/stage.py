from __future__ import annotations

"""Stage decorator configuration and repair-policy validation."""

import inspect
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from accentor.configure.permissions import PermissionIntent

_LOCAL_EXECUTION = "local"
_AGENT_EXECUTION = "agent"
_EXECUTION_ALIASES = {
    "local": _LOCAL_EXECUTION,
    "python": _LOCAL_EXECUTION,
    "agent": _AGENT_EXECUTION,
    "agentic": _AGENT_EXECUTION,
    "dispatch": _AGENT_EXECUTION,
}
_REPAIR_EXAMPLE = (
    "on_error={ValueError: {'response': 'agent_repair', 'agent': repair_agent, "
    "'goal': 'Repair the failing stage.', 'readable': ['src/app.py'], "
    "'editable': ['src/app.py'], 'validators': [validator]}}"
)

@dataclass(frozen=True, slots=True)
class StageRepairPolicy:
    """Validated public repair policy shape for later execution layers."""

    exception_type: type[BaseException]
    response: str
    agent: Any
    goal: str | None = None
    prompt: str | Callable[..., Any] | None = None
    readable: tuple[Any, ...] = ()
    editable: tuple[Any, ...] = ()
    validators: tuple[Any, ...] = ()
    network: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_type": self.exception_type.__name__,
            "response": self.response,
            "agent": _agent_name(self.agent),
            "goal": self.goal,
            "prompt": _callable_name(self.prompt),
            "readable": [_plain_value(path) for path in self.readable],
            "editable": [_plain_value(path) for path in self.editable],
            "validators": [_callable_name(validator) for validator in self.validators],
            "network": _plain_value(self.network),
            "metadata": _plain_value(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class StageConfig:
    """Normalized metadata attached to decorated stage wrappers."""

    name: str
    execution: str
    agent: Any = None
    validators: tuple[Any, ...] = ()
    max_attempts: int = 1
    inject_criteria: bool = False
    router: Any = None
    route_candidates: tuple[Any, ...] = ()
    readable: tuple[Any, ...] = ()
    editable: tuple[Any, ...] = ()
    network: Any = None
    observation: Any = None
    redaction_report: bool = False
    on_error: Mapping[type[BaseException], StageRepairPolicy] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def repair_policies(self) -> tuple[StageRepairPolicy, ...]:
        return tuple(self.on_error.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "execution": self.execution,
            "agent": _agent_name(self.agent) if self.agent is not None else None,
            "validators": [_callable_name(validator) for validator in self.validators],
            "max_attempts": self.max_attempts,
            "inject_criteria": self.inject_criteria,
            "router": _callable_name(self.router) if self.router is not None else None,
            "route_candidates": [_route_candidate_name(candidate) for candidate in self.route_candidates],
            "readable": [_plain_value(path) for path in self.readable],
            "editable": [_plain_value(path) for path in self.editable],
            "network": _plain_value(self.network),
            "observation": _plain_value(self.observation),
            "redaction_report": self.redaction_report,
            "on_error": {
                policy.exception_type.__name__: policy.to_dict()
                for policy in self.repair_policies
            },
            "metadata": _plain_value(self.metadata),
        }


def build_stage_config(
    func: Callable[..., Any],
    *,
    name: str | None = None,
    execution: str | None = None,
    agent: Any = None,
    validators: Iterable[Any] | Any | None = None,
    max_attempts: int = 1,
    inject_criteria: bool = False,
    router: Any = None,
    route_candidates: Iterable[Any] | Any | None = None,
    readable: Any = None,
    editable: Any = None,
    network: Any = None,
    observation: Any = None,
    redaction_report: bool = False,
    on_error: Mapping[Any, Any] | None = None,
    permissions: PermissionIntent | Mapping[str, Any] | None = None,
    **metadata: Any,
) -> StageConfig:
    """Return normalized stage metadata or raise ``StageConfigurationError``."""

    stage_name = _stage_name(func, name)
    normalized_execution = _normalize_execution(stage_name, execution, agent)
    validator_tuple = _as_tuple(validators, field_name="validators")
    readable_tuple = _normalize_path_declaration(stage_name, "file", "readable", readable)
    editable_tuple = _normalize_path_declaration(stage_name, "write", "editable", editable)
    network_value = _normalize_network(stage_name, network)
    router_value, route_candidate_tuple = _normalize_routing(stage_name, router, route_candidates)

    if permissions is not None:
        permission_intent = PermissionIntent.from_any(permissions)
        readable_tuple = (*readable_tuple, *permission_intent.readable)
        editable_tuple = (*editable_tuple, *permission_intent.editable)
        if network is None:
            network_value = permission_intent.network

    _validate_max_attempts(stage_name, max_attempts)
    _validate_agent(stage_name, normalized_execution, agent)
    _validate_observation(stage_name, observation, redaction_report)

    repair_policies = _normalize_repair_policies(
        stage_name,
        on_error,
        stage_readable=readable_tuple,
        stage_editable=editable_tuple,
        stage_network=network_value,
    )
    if repair_policies and normalized_execution != _LOCAL_EXECUTION:
        raise StageConfigurationError(
            stage_name,
            "repair",
            ("execution='local'",),
            "@stage(name='parse_orders', readable=[...], editable=[...], on_error={ValueError: {...}})",
        )

    return StageConfig(
        name=stage_name,
        execution=normalized_execution,
        agent=agent,
        validators=validator_tuple,
        max_attempts=max_attempts,
        inject_criteria=bool(inject_criteria),
        router=router_value,
        route_candidates=route_candidate_tuple,
        readable=readable_tuple,
        editable=editable_tuple,
        network=network_value,
        observation=observation,
        redaction_report=bool(redaction_report),
        on_error={policy.exception_type: policy for policy in repair_policies},
        metadata=dict(metadata),
    )


def _stage_name(func: Callable[..., Any], name: str | None) -> str:
    selected = name or getattr(func, "__name__", None)
    if not isinstance(selected, str) or not selected:
        raise StageConfigurationError(
            "<unknown>",
            "stage",
            ("name",),
            "@stage(name='parse_orders')",
        )
    return selected


def _normalize_execution(stage_name: str, execution: str | None, agent: Any) -> str:
    inferred = _AGENT_EXECUTION if agent is not None else _LOCAL_EXECUTION
    if execution is None:
        return inferred
    normalized = _EXECUTION_ALIASES.get(str(execution).lower().strip())
    if normalized is None:
        raise StageConfigurationError(
            stage_name,
            "execution",
            ("execution",),
            "@stage(execution='local') or @stage(execution='agent', agent=agent)",
        )
    if normalized == _LOCAL_EXECUTION and agent is not None:
        raise StageConfigurationError(
            stage_name,
            "agent",
            ("execution",),
            "@stage(agent=agent) or @stage(execution='local')",
        )
    return normalized


def _validate_agent(stage_name: str, execution: str, agent: Any) -> None:
    if execution != _AGENT_EXECUTION:
        return
    if agent is None or not callable(getattr(agent, "run", None)):
        raise StageConfigurationError(
            stage_name,
            "agent",
            ("agent", "agent.run"),
            "@stage(agent=MockAgent(responses=['{\"ok\": true}']))",
        )


def _validate_max_attempts(stage_name: str, max_attempts: int) -> None:
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise StageConfigurationError(
            stage_name,
            "retry",
            ("max_attempts",),
            "@stage(max_attempts=2)",
        )


def _normalize_routing(
    stage_name: str,
    router: Any,
    route_candidates: Iterable[Any] | Any | None,
) -> tuple[Any, tuple[Any, ...]]:
    candidates = _as_tuple(route_candidates, field_name="route_candidates")
    if router is None:
        if candidates:
            raise StageConfigurationError(
                stage_name,
                "routing",
                ("router",),
                "@stage(router=ticket_router, route_candidates=[RouteCandidate(name='technical', context='...')])",
            )
        return None, ()
    if not callable(router):
        raise StageConfigurationError(
            stage_name,
            "routing",
            ("router",),
            "@stage(router=ticket_router, route_candidates=[RouteCandidate(name='technical', context='...')])",
        )
    if not candidates:
        raise StageConfigurationError(
            stage_name,
            "routing",
            ("route_candidates",),
            "@stage(router=ticket_router, route_candidates=[RouteCandidate(name='technical', context='...')])",
        )
    return router, candidates


def _normalize_path_declaration(stage_name: str, area: str, field_name: str, value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if value is True or value == {}:
        raise StageConfigurationError(
            stage_name,
            area,
            (field_name,),
            f"@stage({field_name}=['path/to/file'])",
        )
    items = _as_tuple(value, field_name=field_name)
    if not items and _declared_empty(value):
        raise StageConfigurationError(
            stage_name,
            area,
            (field_name,),
            f"@stage({field_name}=['path/to/file'])",
        )
    return items


def _normalize_network(stage_name: str, value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        meaningful = {
            "enabled",
            "network",
            "allow_network",
            "search",
            "allow_search",
            "allowed_hosts",
            "allow_hosts",
            "allowlist",
            "host_allowlist",
            "denied_hosts",
            "deny_hosts",
            "denylist",
            "host_denylist",
        }
        if not any(key in value for key in meaningful):
            raise StageConfigurationError(
                stage_name,
                "network",
                ("enabled/search/hosts",),
                "@stage(network={'search': True}) or @stage(network=False)",
            )
        return value
    raise StageConfigurationError(
        stage_name,
        "network",
        ("network",),
        "@stage(network={'search': True}) or @stage(network=False)",
    )


def _validate_observation(stage_name: str, observation: Any, redaction_report: bool) -> None:
    if observation is None:
        return
    if observation is True or observation == {}:
        raise StageConfigurationError(
            stage_name,
            "sensitive-observation",
            ("observation", "redaction_report"),
            "@stage(observation='sensitive') or @stage(redaction_report=True)",
        )
    if isinstance(observation, str):
        if observation in {"normal", "sensitive"}:
            return
        raise StageConfigurationError(
            stage_name,
            "sensitive-observation",
            ("observation",),
            "@stage(observation='sensitive')",
        )
    if isinstance(observation, Mapping):
        if observation.get("sensitive") is True or observation.get("mode") in {"normal", "sensitive"}:
            return
    if redaction_report:
        return
    raise StageConfigurationError(
        stage_name,
        "sensitive-observation",
        ("observation", "redaction_report"),
        "@stage(observation='sensitive') or @stage(redaction_report=True)",
    )


def _normalize_repair_policies(
    stage_name: str,
    on_error: Mapping[Any, Any] | None,
    *,
    stage_readable: tuple[Any, ...],
    stage_editable: tuple[Any, ...],
    stage_network: Any,
) -> tuple[StageRepairPolicy, ...]:
    if on_error is None:
        return ()
    if not isinstance(on_error, Mapping) or not on_error:
        raise StageConfigurationError(stage_name, "repair", ("on_error",), _REPAIR_EXAMPLE)

    policies: list[StageRepairPolicy] = []
    for exception_type, raw_policy in on_error.items():
        if not isinstance(exception_type, type) or not issubclass(exception_type, BaseException):
            raise StageConfigurationError(stage_name, "repair", ("ExceptionType",), _REPAIR_EXAMPLE)
        if not isinstance(raw_policy, Mapping):
            raise StageConfigurationError(stage_name, "repair", ("policy mapping",), _REPAIR_EXAMPLE)

        policy = dict(raw_policy)
        response = policy.get("response")
        agent = policy.get("agent")
        goal = policy.get("goal")
        prompt = policy.get("prompt")
        readable = _policy_scope(policy, "readable", stage_readable)
        editable = _policy_scope(policy, "editable", stage_editable)
        validators = _as_tuple(policy.get("validators"), field_name="validators")
        network = policy.get("network", stage_network)

        missing: list[str] = []
        if not isinstance(response, str) or not response:
            missing.append("response")
        if agent is None or not callable(getattr(agent, "run", None)):
            missing.append("agent")
        if not goal and prompt is None:
            missing.append("goal/prompt")
        if not readable:
            missing.append("readable")
        if not editable:
            missing.append("editable")
        if not validators:
            missing.append("validators")

        if missing:
            raise StageConfigurationError(stage_name, "repair", missing, _REPAIR_EXAMPLE)

        policies.append(
            StageRepairPolicy(
                exception_type=exception_type,
                response=response,
                agent=agent,
                goal=str(goal) if goal is not None else None,
                prompt=prompt,
                readable=readable,
                editable=editable,
                validators=validators,
                network=network,
                metadata={
                    str(key): _plain_value(value)
                    for key, value in policy.items()
                    if key
                    not in {
                        "response",
                        "agent",
                        "goal",
                        "prompt",
                        "readable",
                        "editable",
                        "validators",
                        "network",
                    }
                },
            )
        )
    return tuple(policies)


def _policy_scope(policy: Mapping[str, Any], field_name: str, fallback: tuple[Any, ...]) -> tuple[Any, ...]:
    if field_name not in policy:
        return fallback
    value = policy[field_name]
    if value is True or value == {}:
        return ()
    return _as_tuple(value, field_name=field_name)


def _as_tuple(value: Any, *, field_name: str) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, Path, Mapping)):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _declared_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, bytes, Path, Mapping)):
        return False
    try:
        return len(value) == 0
    except TypeError:
        return False


def _call_with_optional_ctx(func: Callable[..., Any], ctx: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(*args, **kwargs)
    if "ctx" not in signature.parameters or "ctx" in kwargs:
        return func(*args, **kwargs)
    return func(*args, ctx=ctx, **kwargs)


def _plain_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    if callable(value):
        return _callable_name(value)
    return value


def _agent_name(agent: Any) -> str:
    return str(getattr(agent, "name", None) or type(agent).__name__)


def _route_candidate_name(candidate: Any) -> str:
    name = getattr(candidate, "name", None)
    if name is not None:
        return str(name)
    if isinstance(candidate, Mapping) and "name" in candidate:
        return str(candidate["name"])
    return type(candidate).__name__


def _callable_name(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(getattr(value, "__name__", None) or type(value).__name__)


import ast
import inspect
import os
import shutil
import tempfile
import traceback
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from accentor.configure.prompt import PromptCompiler
from accentor.core.composition.gates import build_validation_report, validate_candidate
from accentor.core.composition.routing import (
    append_routing_record,
    kwargs_with_routed_context,
    resolve_route,
    routing_record,
)
from accentor.core.decorators.workflow import (
    _CURRENT_RUNTIME,
    _RunState,
    _WorkflowStageFailure,
    _accepts_parameter,
    _call_with_optional_ctx,
    _create_runtime,
    _current_runtime,
    _finalize_runtime_result,
)
from accentor.core.task.diagnostics import Diagnostic
from accentor.core.task.events import TaskEvent
from accentor.core.task.results import ArtifactReference, TaskResult
from accentor.dispatch.agents.base import AgentCapabilities, AgentRequest, AgentRunResult
from accentor.dispatch.workspace import (
    LocalWorkspaceBackend,
    StagedWorkspace,
    WorkspacePlan,
    diff_workspaces,
    write_diff_scope_artifacts,
)
from accentor.record.artifacts import ArtifactRecord


class StageConfigurationError(ValueError):
    """Raised when a stage declaration is incomplete or contradictory."""

    def __init__(
        self,
        stage_name: str,
        area: str,
        missing_fields: Sequence[str],
        example: str,
    ) -> None:
        self.stage_name = stage_name
        self.area = area
        self.missing_fields = tuple(missing_fields)
        self.example = example
        fields = ", ".join(self.missing_fields)
        super().__init__(
            f"Stage {stage_name!r} is missing required {area} configuration: "
            f"{fields}. Example: {example}."
        )


class StageValidationError(RuntimeError):
    """Raised by callers that explicitly ask to unwrap a failed stage result."""

    def __init__(
        self,
        message_or_result: TaskResult | str,
        *,
        task_result: TaskResult | None = None,
        **kwargs: Any,
    ) -> None:
        if "result" in kwargs:
            task_result = kwargs["result"]
        if isinstance(message_or_result, TaskResult):
            task_result = message_or_result
            message: str | None = None
        else:
            message = message_or_result
        self.result = message_or_result
        if task_result is not None:
            self.result = task_result
            if message is None and task_result.diagnostics:
                diagnostic = task_result.diagnostics[0]
                message = f"Stage validation failed: [{diagnostic.code}] {diagnostic.message}"
        if message is None:
            message = "Stage validation failed"
        super().__init__(message)


@dataclass(frozen=True)
class _StageConfig:
    name: str | None
    execution: str | None
    agent: Any = None
    validators: tuple[Any, ...] = ()
    max_attempts: int = 1
    inject_criteria: bool = False
    router: Any = None
    route_candidates: tuple[Any, ...] = ()
    observation: str | None = None
    redaction_report: bool = False
    on_error: Mapping[Any, Any] | None = None
    readable: tuple[Any, ...] = ()
    editable: tuple[Any, ...] = ()
    network: Any = None
    timeout_seconds: float | None = None
    provider_options: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class _RepairWorkspace:
    plan: WorkspacePlan
    staged: StagedWorkspace
    before_root: Path


def _runtime_as_tuple(value: Iterable[Any] | Any | None) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or callable(value) or hasattr(value, "validate"):
        return (value,)
    return tuple(value)


def _runtime_execution(execution: str | None, *, agent: Any, stage_name: str) -> str:
    if execution is None:
        return "agent" if agent is not None else "local"
    normalized = str(execution).replace("_", "-").lower()
    aliases = {
        "agent": "agent",
        "agentic": "agent",
        "dispatch": "agent",
        "local": "local",
        "python": "local",
    }
    if normalized not in aliases:
        raise StageConfigurationError(
            stage_name,
            "execution",
            ["execution"],
            "@stage(execution='local') or @stage(agent=adapter)",
        )
    selected = aliases[normalized]
    if selected == "agent" and agent is None:
        raise StageConfigurationError(
            stage_name,
            "agent",
            ["agent"],
            "@stage(agent=MockAgent(responses=['{}']))",
        )
    if selected == "local" and agent is not None:
        raise StageConfigurationError(
            stage_name,
            "execution",
            ["execution"],
            "@stage(execution='agent', agent=adapter)",
        )
    return selected


def _runtime_max_attempts(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_attempts must be an int")
    if value < 1:
        raise ValueError("max_attempts must be at least 1")
    return value


def _agent_name(agent: Any) -> str:
    return str(getattr(agent, "name", agent.__class__.__name__))


def _artifact_to_dict(artifact: ArtifactReference) -> dict[str, Any]:
    if isinstance(artifact, ArtifactRecord):
        return artifact.to_dict()
    return dict(artifact)


def _diagnostic_from_exception(
    *,
    code: str,
    stage_name: str,
    exc: BaseException,
    source: str,
) -> Diagnostic:
    return Diagnostic.error(
        code,
        f"Stage {stage_name!r} raised {type(exc).__name__}: {exc}",
        source=source,
        details={"exception_type": type(exc).__name__},
    )


def _coerce_diagnostics(items: Sequence[Any], *, source: str, default_code: str) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    for item in items:
        if isinstance(item, Diagnostic):
            diagnostics.append(item)
            continue
        if isinstance(item, Mapping):
            diagnostics.append(Diagnostic(**item))
            continue
        to_dict = getattr(item, "to_dict", None)
        if callable(to_dict):
            payload = to_dict()
            if isinstance(payload, Mapping):
                diagnostics.append(Diagnostic(**payload))
                continue
        diagnostics.append(
            Diagnostic.error(
                default_code,
                str(item),
                source=source,
            )
        )
    return tuple(diagnostics)


def _permissions_payload(config: _StageConfig) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if config.readable:
        payload["readable"] = [str(path) for path in config.readable]
    if config.editable:
        payload["editable"] = [str(path) for path in config.editable]
    if config.network is not None:
        payload["network"] = config.network
    return payload


def _diagnostic_from_routing(diagnostic: Any) -> Diagnostic:
    payload = diagnostic.to_dict() if callable(getattr(diagnostic, "to_dict", None)) else dict(diagnostic)
    return Diagnostic(
        code=str(payload.get("code") or "routing.no_match"),
        message=str(payload.get("message") or "Routing did not select a configured candidate."),
        severity=str(payload.get("severity") or "error"),
        source=str(payload.get("source") or "routing"),
        hint=payload.get("hint"),
        details=payload.get("details") or {},
    )


def _prepare_routed_call(
    function: Callable[..., Any],
    config: _StageConfig,
    state: _RunState,
    *,
    stage_name: str,
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
) -> tuple[dict[str, Any], TaskResult | None]:
    if config.router is None:
        return dict(kwargs), None

    resolution = resolve_route(
        config.router,
        stage_name=stage_name,
        function=function,
        args=args,
        kwargs=kwargs,
        route_candidates=config.route_candidates,
        run_id=state.context.run_id,
    )
    state.context = state.context.derive(
        routing={
            "stage": stage_name,
            "selected": resolution.selected,
            "omitted": list(resolution.omitted),
            "candidates": list(resolution.context.candidate_names),
        }
    )
    record = routing_record(
        resolution,
        run_id=state.context.run_id,
        stage=stage_name,
        task=state.task_id,
        workflow=state.workflow,
    )
    state.emit(
        TaskEvent.routing_decided(
            routing=record,
            workflow=state.workflow,
            task=state.task_id,
            stage=stage_name,
        )
    )

    artifacts: list[ArtifactReference] = []
    if state.artifact_store is not None:
        artifact = append_routing_record(
            state.artifact_store,
            record,
            append=state.routing_decisions_started,
        )
        state.routing_decisions_started = True
        state.add_artifact(artifact, stage=stage_name)
        artifacts.append(artifact)

    if not resolution.ok:
        diagnostics = tuple(_diagnostic_from_routing(diagnostic) for diagnostic in resolution.diagnostics)
        if not diagnostics:
            diagnostics = (
                Diagnostic.error(
                    "routing.no_match",
                    "Routing did not select a configured candidate.",
                    source="routing",
                ),
            )
        result = TaskResult(
            ok=False,
            diagnostics=diagnostics,
            attempt_count=1,
            artifacts=artifacts,
        )
        state.attempt_count = max(state.attempt_count, 1)
        return dict(kwargs), result

    return kwargs_with_routed_context(function, kwargs, resolution), None


def _stage_context(state: _RunState, stage_name: str, attempt: int = 0) -> Any:
    return state.context.derive(stage=stage_name, attempt=attempt)


def _emit_stage_completed(
    state: _RunState,
    *,
    stage_name: str,
    result: TaskResult,
    attempt: int | None = None,
    validation: Mapping[str, Any] | None = None,
) -> None:
    state.emit(
        TaskEvent.stage_completed(
            stage=stage_name,
            workflow=state.workflow,
            task=state.task_id,
            attempt=attempt,
            status="completed" if result.ok else "failed",
            diagnostics=result.diagnostics,
            artifacts=[_artifact_to_dict(artifact) for artifact in result.artifacts],
            validation=validation,
        )
    )


def _write_prompt_attempt(
    state: _RunState,
    *,
    stage_name: str,
    attempt: int,
    prompt: str,
    observation: str | None,
) -> ArtifactReference | None:
    if state.artifact_store is None:
        return None
    text = "[REDACTED]\n" if observation == "sensitive" else prompt
    artifact = state.artifact_store.write_text(
        f"prompt_attempt_{attempt}.md",
        text if text.endswith("\n") else f"{text}\n",
        content_type="text/markdown",
    )
    state.add_artifact(artifact, stage=stage_name, attempt=attempt)
    return artifact


def _write_redaction_report(
    state: _RunState,
    *,
    stage_name: str,
    args: Sequence[Any],
    output: Any,
) -> ArtifactReference | None:
    if state.artifact_store is None:
        return None
    input_text = args[0] if args and isinstance(args[0], str) else None
    output_text = output if isinstance(output, str) else None
    token_counts: dict[str, int] = {}
    if output_text is not None:
        for token in ("[EMAIL]", "[PHONE]", "[ACCOUNT]", "[AMOUNT]", "[REDACTED]"):
            count = output_text.count(token)
            if count:
                token_counts[token] = count
    report = {
        "stage": stage_name,
        "changed": bool(input_text is not None and output_text is not None and input_text != output_text),
        "input_character_count": len(input_text) if input_text is not None else None,
        "output_character_count": len(output_text) if output_text is not None else None,
        "replacement_token_counts": token_counts,
    }
    artifact = state.artifact_store.write_json("redaction_report.json", report)
    state.add_artifact(artifact, stage=stage_name)
    return artifact


def _run_validation(
    state: _RunState,
    *,
    stage_name: str,
    candidates: Sequence[Any] | Any,
    validators: Sequence[Any],
    max_attempts: int,
    metadata: Mapping[str, Any] | None = None,
) -> TaskResult:
    report = build_validation_report(
        candidates,
        validators,
        max_attempts=max_attempts,
        artifact_store=state.artifact_store,
        artifact_root=state.context.artifact_root,
        workflow=state.workflow,
        task=state.task_id,
        stage=stage_name,
        write_reports=state.artifact_store is not None,
        metadata=metadata,
    )
    for event in report.events:
        state.emit(event)
    state.add_artifacts(report.artifacts, stage=stage_name)
    state.attempt_count = max(state.attempt_count, report.attempt_count)
    return report.to_task_result()


def _matching_repair_policy(config: _StageConfig, exc: BaseException) -> StageRepairPolicy | None:
    for policy in (config.on_error or {}).values():
        if isinstance(policy, StageRepairPolicy) and isinstance(exc, policy.exception_type):
            return policy
    return None


def _safe_exception_message(exc: BaseException, *, limit: int = 4000) -> tuple[str, bool]:
    try:
        message = str(exc)
    except Exception:  # noqa: BLE001 - hostile exception objects must serialize.
        message = type(exc).__name__
    if len(message) <= limit:
        return message, False
    return f"{message[:limit]}...[truncated]", True


def _traceback_summary(exc: BaseException) -> list[dict[str, Any]]:
    frames = traceback.extract_tb(exc.__traceback__)
    return [
        {
            "filename": frame.filename,
            "line": frame.lineno,
            "function": frame.name,
        }
        for frame in frames
    ]


def _validator_names(validators: Sequence[Any]) -> list[str]:
    names: list[str] = []
    for validator in validators:
        name = getattr(validator, "__name__", None)
        if name is None:
            name = validator.__class__.__name__
        names.append(str(name))
    return names


def _validator_target_paths(validators: Sequence[Any]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for validator in validators:
        path = getattr(validator, "path", None)
        if path is None:
            continue
        text = str(_plain_value(path))
        if text not in seen:
            paths.append(text)
            seen.add(text)
    return paths


def _repair_scope(policy: StageRepairPolicy) -> dict[str, Any]:
    return {
        "readable": [str(path) for path in policy.readable],
        "editable": [str(path) for path in policy.editable],
        "network": _plain_value(policy.network),
    }


def _write_repair_incident(
    state: _RunState,
    *,
    stage_name: str,
    policy: StageRepairPolicy,
    exc: BaseException,
) -> tuple[dict[str, Any], list[ArtifactReference]]:
    artifacts: list[ArtifactReference] = []
    message, truncated = _safe_exception_message(exc)
    incident = {
        "schema_version": 1,
        "stage": stage_name,
        "workflow": state.workflow,
        "task": state.task_id,
        "run_id": state.context.run_id,
        "attempt": 0,
        "exception_type": type(exc).__name__,
        "exception_module": type(exc).__module__,
        "message": message,
        "message_redacted": False,
        "message_truncated": truncated,
        "traceback_summary": _traceback_summary(exc),
        "trigger": {
            "exception_type": policy.exception_type.__name__,
            "response": policy.response,
        },
        "repair": {
            "response": policy.response,
            "agent": _agent_name(policy.agent),
            "goal": policy.goal,
            "prompt": _callable_name(policy.prompt),
            "validators": _validator_names(policy.validators),
            "network": _plain_value(policy.network),
        },
        "scope": _repair_scope(policy),
        "safe_metadata": {
            "repair_supported": _agent_supports_repair(policy.agent),
        },
        "artifact": "incident.json" if state.artifact_store is not None else None,
    }
    if state.artifact_store is not None:
        artifact = state.artifact_store.write_json("incident.json", incident)
        state.add_artifact(artifact, stage=stage_name)
        artifacts.append(artifact)

    state.emit(
        TaskEvent.repair_recorded(
            repair={
                "stage": stage_name,
                "exception_type": type(exc).__name__,
                "response": policy.response,
                "incident_artifact": "incident.json" if state.artifact_store is not None else None,
                "readable": [str(path) for path in policy.readable],
                "editable": [str(path) for path in policy.editable],
            },
            workflow=state.workflow,
            task=state.task_id,
            stage=stage_name,
            attempt=0,
            status="incident_captured",
        )
    )
    return incident, artifacts


def _agent_supports_repair(agent: Any) -> bool:
    if _agent_name(agent) == "MockAgent" or agent.__class__.__module__.endswith(".mock.adapter"):
        return False
    if bool(getattr(agent, "supports_repair", False) or getattr(agent, "repair_capable", False)):
        return True
    capabilities = AgentCapabilities.from_any(getattr(agent, "capabilities", None))
    return bool(capabilities.supports_files)


def _repair_failure_result(
    state: _RunState,
    *,
    code: str,
    message: str,
    stage_name: str,
    details: Mapping[str, Any],
    artifacts: Sequence[ArtifactReference] = (),
    diagnostics: Sequence[Diagnostic] = (),
    attempt_count: int = 1,
    hint: str | None = None,
) -> TaskResult:
    diagnostic = Diagnostic.error(
        code,
        message,
        source="stage",
        hint=hint,
        details={"stage": stage_name, **dict(details)},
    )
    state.attempt_count = max(state.attempt_count, attempt_count)
    state.emit(
        TaskEvent.repair_recorded(
            repair={"stage": stage_name, "code": code, **dict(details)},
            workflow=state.workflow,
            task=state.task_id,
            stage=stage_name,
            attempt=attempt_count - 1,
            status="rejected",
            diagnostics=(diagnostic, *diagnostics),
        )
    )
    return TaskResult(
        ok=False,
        best_output=None,
        diagnostics=(diagnostic, *diagnostics),
        attempt_count=attempt_count,
        artifacts=tuple(artifacts),
    )


def _common_workspace_root(paths: Sequence[Any]) -> Path:
    absolute_paths: list[Path] = []
    for item in paths:
        raw = Path(os.fspath(item))
        absolute_paths.append(raw if raw.is_absolute() else Path.cwd() / raw)
    if not absolute_paths:
        return Path.cwd().resolve(strict=False)
    if len(absolute_paths) == 1:
        path = absolute_paths[0].resolve(strict=False)
        return path.parent if path.suffix or path.exists() and path.is_file() else path
    common = Path(os.path.commonpath([str(path.resolve(strict=False)) for path in absolute_paths]))
    return common.parent if common.exists() and common.is_file() else common


def _prepare_repair_workspace(
    *,
    stage_name: str,
    policy: StageRepairPolicy,
) -> _RepairWorkspace:
    declared = (*policy.readable, *policy.editable)
    root = _common_workspace_root(declared)
    plan = WorkspacePlan(
        root=root,
        readable=policy.readable,
        editable=policy.editable,
        metadata={"stage": stage_name, "repair": True},
    )
    backend = LocalWorkspaceBackend()
    staged = backend.stage(plan)
    before_root = Path(tempfile.mkdtemp(prefix="accentor-repair-before-"))
    shutil.copytree(staged.root, before_root, dirs_exist_ok=True)
    return _RepairWorkspace(plan=plan, staged=staged, before_root=before_root)


def _repair_prompt(
    *,
    stage_name: str,
    policy: StageRepairPolicy,
    incident: Mapping[str, Any],
    workspace: _RepairWorkspace,
) -> str:
    if isinstance(policy.prompt, str) and policy.prompt:
        prompt = policy.prompt
    else:
        prompt = policy.goal or "Repair the failing stage."
    validator_targets = _validator_target_paths(policy.validators)
    return "\n".join(
        [
            f"Repair stage: {stage_name}",
            f"Goal: {prompt}",
            f"Exception: {incident.get('exception_type')}: {incident.get('message')}",
            "",
            "Readable files:",
            *[f"- {path}" for path in workspace.plan.readable],
            "",
            "Editable files:",
            *[f"- {path}" for path in workspace.plan.editable],
            "",
            "Validation requirements:",
            *[f"- {name}" for name in _validator_names(policy.validators)],
            "",
            "Validation target files:",
            *(f"- {path}" for path in validator_targets),
            "",
            "Edit only declared editable files in the provided workspace.",
            "Do not create, delete, or modify validation target files during the repair dispatch.",
            "Accentor will rerun the repaired stage or workflow after diff-scope acceptance to produce task outputs.",
            "Leave the staged workspace changed only at editable paths; generated files left behind will be rejected.",
            "Acceptance requires an in-scope diff and successful rerun validation.",
        ]
    )


def _write_repair_diff_artifacts(
    state: _RunState,
    *,
    stage_name: str,
    workspace: _RepairWorkspace,
) -> tuple[Any, list[ArtifactReference]]:
    artifacts: list[ArtifactReference] = []
    if state.artifact_store is not None:
        report = write_diff_scope_artifacts(
            state.artifact_store,
            workspace.before_root,
            workspace.staged.root,
            editable=workspace.plan.editable,
        )
        patch = state.artifact_store.record("proposed_diff.patch", content_type="text/x-patch")
        verdict = state.artifact_store.record("diff_scope_verdict.json", content_type="application/json")
        state.add_artifact(patch, stage=stage_name, attempt=1)
        state.add_artifact(verdict, stage=stage_name, attempt=1)
        artifacts.extend([patch, verdict])
    else:
        report = diff_workspaces(
            workspace.before_root,
            workspace.staged.root,
            editable=workspace.plan.editable,
        )
    state.emit(
        TaskEvent.repair_recorded(
            repair={
                "stage": stage_name,
                "diff_scope_ok": report.verdict.ok,
                "changed_paths": list(report.verdict.changed_paths),
                "violating_paths": list(report.verdict.violating_paths),
                "patch_available": report.verdict.patch_available,
            },
            workflow=state.workflow,
            task=state.task_id,
            stage=stage_name,
            attempt=1,
            status="diff_scope_checked",
        )
    )
    return report, artifacts


def _staged_relative_path(workspace: _RepairWorkspace, value: Any) -> str | None:
    try:
        source = workspace.plan.source_path(value)
        relative = source.relative_to(workspace.plan.root).as_posix()
    except Exception:  # noqa: BLE001 - non-path user values are left alone.
        return None
    return relative if relative in set(workspace.staged.list_files()) else None


def _map_value_to_staged_workspace(workspace: _RepairWorkspace, value: Any) -> Any:
    if isinstance(value, Path):
        relative = _staged_relative_path(workspace, value)
        return workspace.staged.path(relative) if relative is not None else value
    if isinstance(value, os.PathLike):
        relative = _staged_relative_path(workspace, value)
        return workspace.staged.path(relative) if relative is not None else value
    if isinstance(value, str):
        relative = _staged_relative_path(workspace, value)
        return str(workspace.staged.path(relative)) if relative is not None else value
    if isinstance(value, tuple):
        return tuple(_map_value_to_staged_workspace(workspace, item) for item in value)
    if isinstance(value, list):
        return [_map_value_to_staged_workspace(workspace, item) for item in value]
    if isinstance(value, Mapping):
        return {
            key: _map_value_to_staged_workspace(workspace, item)
            for key, item in value.items()
        }
    return value


def _literal_assignments(path: Path) -> dict[str, Any]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - source refresh is best-effort.
        return {}
    assignments: dict[str, Any] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if value is None:
            continue
        try:
            literal = ast.literal_eval(value)
        except Exception:  # noqa: BLE001 - only literal globals are safe to refresh.
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                assignments[target.id] = literal
    return assignments


def _apply_repaired_literal_globals(
    function: Callable[..., Any],
    workspace: _RepairWorkspace,
) -> dict[str, Any]:
    try:
        function_file = Path(function.__code__.co_filename).resolve(strict=False)
    except Exception:  # noqa: BLE001 - builtins or unusual callables have no source.
        return {}

    originals: dict[str, Any] = {}
    for editable in workspace.plan.editable:
        source_path = workspace.plan.root.joinpath(editable).resolve(strict=False)
        if source_path != function_file:
            continue
        staged_path = workspace.staged.path(editable)
        before = _literal_assignments(source_path)
        after = _literal_assignments(staged_path)
        for name, value in after.items():
            if name not in before or before[name] == value or name not in function.__globals__:
                continue
            if name not in originals:
                originals[name] = function.__globals__[name]
            function.__globals__[name] = value
    return originals


def _restore_globals(function: Callable[..., Any], originals: Mapping[str, Any]) -> None:
    for name, value in originals.items():
        function.__globals__[name] = value


def _rerun_repaired_stage(
    function: Callable[..., Any],
    state: _RunState,
    *,
    stage_name: str,
    workspace: _RepairWorkspace,
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
) -> Any:
    mapped_args = tuple(_map_value_to_staged_workspace(workspace, item) for item in args)
    mapped_kwargs = {
        key: _map_value_to_staged_workspace(workspace, value)
        for key, value in kwargs.items()
    }
    originals = _apply_repaired_literal_globals(function, workspace)
    try:
        return _call_with_optional_ctx(
            function,
            _stage_context(state, stage_name, attempt=1),
            *mapped_args,
            **mapped_kwargs,
        )
    finally:
        _restore_globals(function, originals)


def _execute_repair_attempt(
    function: Callable[..., Any],
    config: _StageConfig,
    state: _RunState,
    *,
    stage_name: str,
    policy: StageRepairPolicy,
    exc: BaseException,
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
) -> TaskResult:
    incident, artifacts = _write_repair_incident(
        state,
        stage_name=stage_name,
        policy=policy,
        exc=exc,
    )

    if policy.response != "agent_repair":
        return _repair_failure_result(
            state,
            code="repair.unsupported",
            message=f"Repair response {policy.response!r} is not supported.",
            stage_name=stage_name,
            details={"response": policy.response, "exception_type": type(exc).__name__},
            artifacts=artifacts,
            hint="Use response='agent_repair' for v1 exception repair.",
        )

    if not _agent_supports_repair(policy.agent):
        return _repair_failure_result(
            state,
            code="repair.unsupported",
            message="Agentic exception repair is not supported by the selected provider.",
            stage_name=stage_name,
            details={
                "exception_type": type(exc).__name__,
                "agent": _agent_name(policy.agent),
                "missing_capability": "supports_files",
            },
            artifacts=artifacts,
            hint="Use a provider that can edit the staged workspace.",
        )

    try:
        workspace = _prepare_repair_workspace(stage_name=stage_name, policy=policy)
    except Exception as workspace_exc:  # noqa: BLE001 - planning failures become diagnostics.
        return _repair_failure_result(
            state,
            code="repair.workspace_failed",
            message=f"Repair workspace preparation failed: {workspace_exc}",
            stage_name=stage_name,
            details={
                "exception_type": type(workspace_exc).__name__,
                "repair_exception_type": type(exc).__name__,
            },
            artifacts=artifacts,
        )

    state.emit(
        TaskEvent.repair_recorded(
            repair={
                "stage": stage_name,
                "agent": _agent_name(policy.agent),
                "workspace_root": str(workspace.staged.root),
                "readable": list(workspace.plan.readable),
                "editable": list(workspace.plan.editable),
            },
            workflow=state.workflow,
            task=state.task_id,
            stage=stage_name,
            attempt=1,
            status="repair_started",
        )
    )

    request = AgentRequest(
        prompt=_repair_prompt(stage_name=stage_name, policy=policy, incident=incident, workspace=workspace),
        workspace=workspace.staged,
        permissions={
            "readable": list(workspace.plan.readable),
            "editable": list(workspace.plan.editable),
            "network": _plain_value(policy.network),
            "sandbox": "workspace-write",
        },
        timeout_seconds=config.timeout_seconds,
        provider_options=config.provider_options,
        metadata={
            "stage": stage_name,
            "workflow": state.workflow,
            "run_id": state.context.run_id,
            "attempt": 1,
            "repair": True,
            "incident_artifact": incident.get("artifact"),
            "readable": list(workspace.plan.readable),
            "editable": list(workspace.plan.editable),
        },
    )
    agent_result = _run_agent(policy.agent, request)
    agent_diagnostics = _coerce_diagnostics(
        agent_result.diagnostics,
        source="agent",
        default_code="agent.diagnostic",
    )
    state.emit(
        TaskEvent.repair_recorded(
            repair={"stage": stage_name, "agent_ok": agent_result.ok},
            workflow=state.workflow,
            task=state.task_id,
            stage=stage_name,
            attempt=1,
            status="agent_completed" if agent_result.ok else "rejected",
            diagnostics=agent_diagnostics,
        )
    )
    if not agent_result.ok:
        return _repair_failure_result(
            state,
            code="repair.dispatch_failed",
            message="Repair agent did not complete successfully.",
            stage_name=stage_name,
            details={"agent": _agent_name(policy.agent), "exception_type": type(exc).__name__},
            artifacts=artifacts,
            diagnostics=agent_diagnostics,
            attempt_count=2,
        )

    diff_report, diff_artifacts = _write_repair_diff_artifacts(
        state,
        stage_name=stage_name,
        workspace=workspace,
    )
    artifacts.extend(diff_artifacts)

    if not diff_report.verdict.changed_paths:
        return _repair_failure_result(
            state,
            code="repair.no_changes",
            message="Repair agent completed without changing staged files.",
            stage_name=stage_name,
            details={"agent": _agent_name(policy.agent), "exception_type": type(exc).__name__},
            artifacts=artifacts,
            diagnostics=agent_diagnostics,
            attempt_count=2,
        )

    if not diff_report.verdict.ok:
        return _repair_failure_result(
            state,
            code="repair.diff_scope_violation",
            message="Repair changed files outside declared editable scope.",
            stage_name=stage_name,
            details={
                "agent": _agent_name(policy.agent),
                "violating_paths": list(diff_report.verdict.violating_paths),
                "changed_paths": list(diff_report.verdict.changed_paths),
            },
            artifacts=artifacts,
            diagnostics=agent_diagnostics,
            attempt_count=2,
        )

    try:
        output = _rerun_repaired_stage(
            function,
            state,
            stage_name=stage_name,
            workspace=workspace,
            args=args,
            kwargs=kwargs,
        )
    except Exception as rerun_exc:  # noqa: BLE001 - failed reruns are structured repair failures.
        return _repair_failure_result(
            state,
            code="repair.rerun_failed",
            message=f"Repaired stage rerun raised {type(rerun_exc).__name__}: {rerun_exc}",
            stage_name=stage_name,
            details={"exception_type": type(rerun_exc).__name__},
            artifacts=artifacts,
            diagnostics=agent_diagnostics,
            attempt_count=2,
        )

    state.attempt_count = max(state.attempt_count, 2)
    state.emit(
        TaskEvent.repair_recorded(
            repair={
                "stage": stage_name,
                "changed_paths": list(diff_report.verdict.changed_paths),
            },
            workflow=state.workflow,
            task=state.task_id,
            stage=stage_name,
            attempt=1,
            status="rerun_started",
        )
    )

    if state.workflow is not None:
        state.pending_repair_validations.append(
            {
                "stage": stage_name,
                "validators": policy.validators,
                "metadata": {
                    "execution": "repair",
                    "initial_exception_type": type(exc).__name__,
                    "diff_scope_ok": diff_report.verdict.ok,
                    "changed_paths": list(diff_report.verdict.changed_paths),
                },
            }
        )
        return TaskResult(
            ok=True,
            output=output,
            best_output=output,
            diagnostics=agent_diagnostics,
            attempt_count=2,
            artifacts=tuple(artifacts),
        )

    validation_result = _run_validation(
        state,
        stage_name=stage_name,
        candidates=output,
        validators=policy.validators,
        max_attempts=1,
        metadata={
            "execution": "repair",
            "initial_exception_type": type(exc).__name__,
            "diff_scope_ok": diff_report.verdict.ok,
            "changed_paths": list(diff_report.verdict.changed_paths),
        },
    )
    diagnostics = (*agent_diagnostics, *validation_result.diagnostics)
    if not validation_result.ok:
        diagnostics = (
            Diagnostic.error(
                "repair.validation_failed",
                "Repaired stage output failed validation.",
                source="stage",
                details={"stage": stage_name},
            ),
            *diagnostics,
        )
    state.emit(
        TaskEvent.repair_recorded(
            repair={
                "stage": stage_name,
                "validation_ok": validation_result.ok,
                "changed_paths": list(diff_report.verdict.changed_paths),
            },
            workflow=state.workflow,
            task=state.task_id,
            stage=stage_name,
            attempt=1,
            status="accepted" if validation_result.ok else "rejected",
            diagnostics=diagnostics,
        )
    )
    return TaskResult(
        ok=validation_result.ok,
        output=validation_result.output if validation_result.ok else None,
        best_output=validation_result.best_output,
        diagnostics=diagnostics,
        attempt_count=max(2, validation_result.attempt_count),
        artifacts=(*artifacts, *validation_result.artifacts),
    )


def _execute_local_stage(
    function: Callable[..., Any],
    config: _StageConfig,
    state: _RunState,
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
) -> TaskResult:
    stage_name = config.name or function.__name__
    context = _stage_context(state, stage_name)
    state.emit(TaskEvent.stage_started(stage=stage_name, workflow=state.workflow, task=state.task_id, attempt=0))
    routed_kwargs, routing_failure = _prepare_routed_call(
        function,
        config,
        state,
        stage_name=stage_name,
        args=args,
        kwargs=kwargs,
    )
    if routing_failure is not None:
        _emit_stage_completed(state, stage_name=stage_name, result=routing_failure, attempt=0)
        return routing_failure
    context = _stage_context(state, stage_name)

    try:
        output = _call_with_optional_ctx(function, context, *args, **routed_kwargs)
    except Exception as exc:  # noqa: BLE001 - stage boundaries return diagnostics.
        policy = _matching_repair_policy(config, exc) if config.on_error else None
        if policy is not None:
            result = _execute_repair_attempt(
                function,
                config,
                state,
                stage_name=stage_name,
                policy=policy,
                exc=exc,
                args=args,
                kwargs=routed_kwargs,
            )
        else:
            result = TaskResult(
                ok=False,
                diagnostics=[
                    _diagnostic_from_exception(
                        code="stage.exception",
                        stage_name=stage_name,
                        exc=exc,
                        source="stage",
                    )
                ],
                attempt_count=1,
            )
            state.attempt_count = max(state.attempt_count, 1)
        _emit_stage_completed(state, stage_name=stage_name, result=result, attempt=0)
        return result

    artifacts: list[ArtifactReference] = []
    if config.redaction_report or stage_name.startswith("redact"):
        artifact = _write_redaction_report(state, stage_name=stage_name, args=args, output=output)
        if artifact is not None:
            artifacts.append(artifact)

    if config.validators:
        result = _run_validation(
            state,
            stage_name=stage_name,
            candidates=output,
            validators=config.validators,
            max_attempts=1,
            metadata={"execution": "local"},
        )
        if artifacts:
            result = TaskResult(
                ok=result.ok,
                output=result.output,
                best_output=result.best_output,
                diagnostics=result.diagnostics,
                attempt_count=result.attempt_count,
                events=result.events,
                artifacts=(*artifacts, *result.artifacts),
            )
        _emit_stage_completed(
            state,
            stage_name=stage_name,
            result=result,
            attempt=0,
            validation={"ok": result.ok, "attempt_count": result.attempt_count},
        )
        return result

    state.attempt_count = max(state.attempt_count, 1)
    result = TaskResult(ok=True, output=output, best_output=output, attempt_count=1, artifacts=artifacts)
    _emit_stage_completed(state, stage_name=stage_name, result=result, attempt=0)
    return result


def _compile_prompt(
    function: Callable[..., Any],
    config: _StageConfig,
    *,
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
    context: Any,
    previous_validation_results: Any,
) -> str:
    call_kwargs = dict(kwargs)
    if _accepts_parameter(function, "ctx") and "ctx" not in call_kwargs:
        call_kwargs["ctx"] = context
    compiled = PromptCompiler(
        validators=config.validators,
        inject_criteria=config.inject_criteria,
    ).compile(
        function,
        args=args,
        kwargs=call_kwargs,
        previous_validation_results=previous_validation_results,
    )
    return compiled.prompt


def _run_agent(agent: Any, request: AgentRequest) -> AgentRunResult:
    run = getattr(agent, "run", None)
    if not callable(run):
        return AgentRunResult.failure(
            f"Agent object {agent!r} does not provide run(request).",
            code="agent.invalid_adapter",
        )
    try:
        result = run(request)
    except Exception as exc:  # noqa: BLE001 - adapter failures become diagnostics.
        return AgentRunResult.failure(
            f"Agent adapter raised {type(exc).__name__}: {exc}",
            code="agent.exception",
            diagnostics=[
                Diagnostic.error(
                    "agent.exception",
                    str(exc) or type(exc).__name__,
                    source="agent",
                    details={"exception_type": type(exc).__name__},
                )
            ],
        )
    if isinstance(result, AgentRunResult):
        return result
    return AgentRunResult(output=str(result), ok=True)


def _execute_agent_stage(
    function: Callable[..., Any],
    config: _StageConfig,
    state: _RunState,
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
) -> TaskResult:
    stage_name = config.name or function.__name__
    state.emit(TaskEvent.stage_started(stage=stage_name, workflow=state.workflow, task=state.task_id, attempt=0))
    routed_kwargs, routing_failure = _prepare_routed_call(
        function,
        config,
        state,
        stage_name=stage_name,
        args=args,
        kwargs=kwargs,
    )
    if routing_failure is not None:
        _emit_stage_completed(state, stage_name=stage_name, result=routing_failure, attempt=0)
        return routing_failure

    candidates: list[str] = []
    agent_diagnostics: list[Diagnostic] = []
    previous_failures: tuple[Any, ...] = ()
    accepted_agent_attempt: int | None = None

    for attempt in range(config.max_attempts):
        context = _stage_context(state, stage_name, attempt)
        state.emit(
            TaskEvent.attempt_started(
                attempt=attempt,
                stage=stage_name,
                workflow=state.workflow,
                task=state.task_id,
                details={"agent": _agent_name(config.agent)},
            )
        )

        try:
            prompt = _compile_prompt(
                function,
                config,
                args=args,
                kwargs=routed_kwargs,
                context=context,
                previous_validation_results=previous_failures,
            )
        except Exception as exc:  # noqa: BLE001 - prompt construction is part of the stage.
            diagnostic = _diagnostic_from_exception(
                code="stage.prompt_failed",
                stage_name=stage_name,
                exc=exc,
                source="stage",
            )
            result = TaskResult(ok=False, diagnostics=[diagnostic], attempt_count=attempt + 1)
            state.attempt_count = max(state.attempt_count, attempt + 1)
            _emit_stage_completed(state, stage_name=stage_name, result=result, attempt=attempt)
            return result

        _write_prompt_attempt(
            state,
            stage_name=stage_name,
            attempt=attempt,
            prompt=prompt,
            observation=config.observation,
        )
        request = AgentRequest(
            prompt=prompt,
            permissions=_permissions_payload(config),
            timeout_seconds=config.timeout_seconds,
            provider_options=config.provider_options,
            metadata={
                "stage": stage_name,
                "attempt": attempt,
                "workflow": state.workflow,
                **dict(config.metadata or {}),
            },
        )
        agent_result = _run_agent(config.agent, request)
        agent_diagnostics.extend(
            _coerce_diagnostics(
                agent_result.diagnostics,
                source="agent",
                default_code="agent.diagnostic",
            )
        )
        candidates.append(agent_result.output)

        attempt_result = validate_candidate(
            agent_result.output,
            config.validators,
            attempt_index=attempt,
            artifact_root=state.context.artifact_root,
            artifact_store=state.artifact_store,
            metadata={"execution": "agent", "agent_ok": agent_result.ok},
        )
        previous_failures = attempt_result.failed_validation_results
        accepted = bool(agent_result.ok and attempt_result.ok)
        if accepted:
            accepted_agent_attempt = attempt
        state.emit(
            TaskEvent.attempt_completed(
                attempt=attempt,
                stage=stage_name,
                workflow=state.workflow,
                task=state.task_id,
                status="accepted" if accepted else "failed",
                diagnostics=(
                    *agent_diagnostics,
                    *attempt_result.diagnostics,
                ),
            )
        )
        if accepted:
            break

    validation_result = _run_validation(
        state,
        stage_name=stage_name,
        candidates=tuple(candidates),
        validators=config.validators,
        max_attempts=len(candidates) or 1,
        metadata={
            "execution": "agent",
            "agent": _agent_name(config.agent),
            "accepted_agent_attempt": accepted_agent_attempt,
        },
    )
    diagnostics = (*agent_diagnostics, *validation_result.diagnostics)
    ok = validation_result.ok and accepted_agent_attempt is not None
    if validation_result.ok and accepted_agent_attempt is None:
        diagnostics = (
            *diagnostics,
            Diagnostic.error(
                "agent.run_failed",
                "Validation passed but no agent attempt completed successfully.",
                source="agent",
            ),
        )

    result = TaskResult(
        ok=ok,
        output=validation_result.output if ok else None,
        best_output=validation_result.best_output,
        diagnostics=diagnostics,
        attempt_count=validation_result.attempt_count,
        artifacts=validation_result.artifacts,
    )
    state.attempt_count = max(state.attempt_count, result.attempt_count)
    _emit_stage_completed(
        state,
        stage_name=stage_name,
        result=result,
        attempt=result.attempt_count - 1 if result.attempt_count else None,
        validation={"ok": result.ok, "attempt_count": result.attempt_count},
    )
    return result


def _execute_stage(
    function: Callable[..., Any],
    config: _StageConfig,
    state: _RunState,
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
) -> TaskResult:
    stage_name = config.name or function.__name__
    execution = _runtime_execution(config.execution, agent=config.agent, stage_name=stage_name)
    if execution == "agent":
        return _execute_agent_stage(function, config, state, args, kwargs)
    return _execute_local_stage(function, config, state, args, kwargs)


def stage(
    _function: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    execution: str | None = None,
    agent: Any = None,
    validators: Iterable[Any] | Any | None = None,
    max_attempts: int = 1,
    inject_criteria: bool = False,
    router: Any = None,
    route_candidates: Iterable[Any] | Any | None = None,
    observation: str | None = None,
    redaction_report: bool = False,
    on_error: Mapping[Any, Any] | None = None,
    readable: Iterable[Any] | Any | None = None,
    editable: Iterable[Any] | Any | None = None,
    network: Any = None,
    timeout_seconds: float | None = None,
    provider_options: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    **_future_options: Any,
) -> Callable[..., Any]:
    """Decorate a local Python or agent-backed stage."""

    _runtime_max_attempts(max_attempts)

    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        public_metadata = dict(_future_options)
        if metadata:
            public_metadata.update(metadata)
        public_config = build_stage_config(
            function,
            name=name,
            execution=execution,
            agent=agent,
            validators=validators,
            max_attempts=max_attempts,
            inject_criteria=inject_criteria,
            router=router,
            route_candidates=route_candidates,
            readable=readable,
            editable=editable,
            network=network,
            observation=observation,
            redaction_report=redaction_report,
            on_error=on_error,
            **public_metadata,
        )
        runtime_config = _StageConfig(
            name=public_config.name,
            execution=public_config.execution,
            agent=public_config.agent,
            validators=public_config.validators,
            max_attempts=public_config.max_attempts,
            inject_criteria=public_config.inject_criteria,
            router=public_config.router,
            route_candidates=public_config.route_candidates,
            observation=public_config.observation,
            redaction_report=public_config.redaction_report,
            on_error=public_config.on_error,
            readable=public_config.readable,
            editable=public_config.editable,
            network=public_config.network,
            timeout_seconds=timeout_seconds,
            provider_options=provider_options,
            metadata=public_config.metadata,
        )
        stage_name = public_config.name
        _runtime_execution(runtime_config.execution, agent=runtime_config.agent, stage_name=stage_name)

        @wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            artifact_root = kwargs.pop("artifact_root", None)
            active_state = _current_runtime()
            if active_state is not None:
                result = _execute_stage(function, runtime_config, active_state, args, kwargs)
                if result.ok:
                    return result.output
                raise _WorkflowStageFailure(result)

            state = _create_runtime(
                workflow=None,
                task_id=stage_name,
                artifact_root=artifact_root,
                metadata={"stage": stage_name},
            )
            token = _CURRENT_RUNTIME.set(state)
            try:
                result = _execute_stage(function, runtime_config, state, args, kwargs)
                if (
                    runtime_config.execution == "local"
                    and not runtime_config.validators
                    and artifact_root is None
                    and result.ok
                ):
                    return result.output
                if (
                    runtime_config.execution == "local"
                    and artifact_root is None
                    and any(diagnostic.code == "repair.unsupported" for diagnostic in result.diagnostics)
                ):
                    raise StageValidationError(
                        (
                            f"Stage '{stage_name}' matched repair policy, but repair execution "
                            "is not implemented in WP-08."
                        ),
                        result=result,
                    )
                return _finalize_runtime_result(state, result)
            finally:
                _CURRENT_RUNTIME.reset(token)

        wrapper.__accentor_stage_config__ = public_config
        return wrapper

    if _function is not None:
        return decorate(_function)
    return decorate


__all__ = [
    "StageConfig",
    "StageConfigurationError",
    "StageRepairPolicy",
    "StageValidationError",
    "build_stage_config",
    "stage",
]
