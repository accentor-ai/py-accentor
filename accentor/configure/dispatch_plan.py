from __future__ import annotations

"""Provider-neutral dispatch planning records."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from accentor.configure.context import FRAMEWORK_INJECTED_NAMES, user_call_args
from accentor.dispatch.agents.base.request import AgentRequest, REDACTED_VALUE
from accentor.dispatch.policy.permissions import PermissionSet
from accentor.dispatch.workspace.plans import WorkspacePlan


class SandboxMode(str, Enum):
    """Provider-neutral sandbox modes recorded by configure-layer plans."""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    NONE = "none"
    EXTERNAL = "external"

    def __str__(self) -> str:
        return self.value


_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "content",
        "customer_note",
        "input",
        "message",
        "password",
        "prompt",
        "request",
        "secret",
        "secret_ref",
        "text",
        "token",
    }
)


def _plain_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return _plain_value(value.value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _plain_value(to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return _plain_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_plain_value(item) for item in sorted(value, key=repr)]
    name = getattr(value, "name", None)
    return str(name if name is not None else type(value).__name__)


def _copy_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType({str(key): _plain_value(item) for key, item in (value or {}).items()})


def _copy_messages(messages: Sequence[Mapping[str, Any]] | None) -> tuple[Mapping[str, Any], ...]:
    return tuple(_copy_mapping(message) for message in (messages or ()))


def _agent_name(agent: Any) -> str | None:
    if agent is None:
        return None
    if isinstance(agent, str):
        return agent
    name = getattr(agent, "name", None)
    return str(name if name is not None else type(agent).__name__)


def _validator_summary(validator: Any) -> dict[str, Any]:
    name = getattr(validator, "name", None)
    if name is None:
        name = getattr(validator, "__name__", None)
    if name is None:
        name = type(validator).__name__
    criteria = getattr(validator, "criteria_description", None)
    if callable(criteria):
        try:
            criteria = criteria()
        except TypeError:
            criteria = None
    if criteria is None:
        criteria = getattr(validator, "criteria", None)
    return {
        "name": str(name),
        "criteria": _plain_value(criteria),
    }


def _routing_summary(routing: Any) -> Any:
    return _plain_value(routing)


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if text_key.lower() in _SENSITIVE_KEYS:
                redacted[text_key] = REDACTED_VALUE
            else:
                redacted[text_key] = _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _normalise_sandbox(value: SandboxMode | str | None) -> SandboxMode | None:
    if value is None:
        return None
    if isinstance(value, SandboxMode):
        return value
    return SandboxMode(str(value).replace("-", "_"))


def _scope_summary(
    workspace: WorkspacePlan | Mapping[str, Any] | None,
    permissions: PermissionSet | Mapping[str, Any] | None,
) -> dict[str, tuple[str, ...]]:
    readable: list[str] = []
    editable: list[str] = []

    if isinstance(workspace, WorkspacePlan):
        readable.extend(workspace.readable)
        editable.extend(workspace.editable)
    elif isinstance(workspace, Mapping):
        readable.extend(str(item) for item in workspace.get("readable", ()))
        editable.extend(str(item) for item in workspace.get("editable", ()))

    if isinstance(permissions, PermissionSet):
        readable.extend(permissions.readable)
        editable.extend(permissions.editable)
    elif isinstance(permissions, Mapping):
        readable.extend(str(item) for item in permissions.get("readable", ()))
        editable.extend(str(item) for item in permissions.get("editable", ()))

    return {
        "readable": tuple(dict.fromkeys(readable)),
        "editable": tuple(dict.fromkeys(editable)),
    }


def _derive_sandbox_mode(
    *,
    workspace: WorkspacePlan | Mapping[str, Any] | None,
    permissions: PermissionSet | Mapping[str, Any] | None,
    explicit: SandboxMode | str | None,
) -> SandboxMode:
    explicit_mode = _normalise_sandbox(explicit)
    if explicit_mode is not None:
        return explicit_mode

    scope = _scope_summary(workspace, permissions)
    if scope["editable"]:
        return SandboxMode.WORKSPACE_WRITE
    if scope["readable"]:
        return SandboxMode.READ_ONLY
    return SandboxMode.NONE


def _workspace_summary(workspace: WorkspacePlan | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if workspace is None:
        return None
    if isinstance(workspace, WorkspacePlan):
        return workspace.summary()
    if isinstance(workspace, Mapping):
        return _plain_value(workspace)
    return _plain_value(workspace)


def _permission_summary(
    permissions: PermissionSet | Mapping[str, Any] | None,
    *,
    agent: Any,
    sandbox_mode: SandboxMode,
) -> dict[str, Any]:
    if permissions is None:
        return {
            "readable": [],
            "editable": [],
            "network": None,
            "commands": None,
            "environment": None,
            "revisions": [],
            "post_run_checks": [],
            "provider_flags": {},
            "sandbox_mode": sandbox_mode.value,
        }
    if isinstance(permissions, PermissionSet):
        data = permissions.to_dict()
        data["post_run_checks"] = list(permissions.post_run_checks())
        data["provider_flags"] = permissions.provider_flags(agent)
        data["sandbox_mode"] = sandbox_mode.value
        return data
    data = _plain_value(permissions)
    if not isinstance(data, dict):
        data = {"value": data}
    data.setdefault("sandbox_mode", sandbox_mode.value)
    return data


@dataclass(frozen=True, slots=True, init=False)
class DispatchPlan:
    """Serializable plan for one provider-neutral agent dispatch attempt."""

    stage: str | None
    agent: Any
    prompt: str | None
    messages: tuple[Mapping[str, Any], ...]
    workspace: WorkspacePlan | Mapping[str, Any] | None
    permissions: PermissionSet | Mapping[str, Any] | None
    routing: Any
    validators: tuple[Any, ...]
    call_args: Mapping[str, Any]
    provider_options: Mapping[str, Any]
    timeout_seconds: float | None
    metadata: Mapping[str, Any]
    sandbox_mode: SandboxMode

    def __init__(
        self,
        *,
        stage: str | None = None,
        agent: Any = None,
        prompt: str | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
        workspace: WorkspacePlan | Mapping[str, Any] | None = None,
        permissions: PermissionSet | Mapping[str, Any] | None = None,
        routing: Any = None,
        validators: Sequence[Any] | None = None,
        call_args: Mapping[str, Any] | None = None,
        provider_options: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        sandbox_mode: SandboxMode | str | None = None,
    ) -> None:
        if stage is not None and (not isinstance(stage, str) or not stage):
            raise ValueError("stage must be a non-empty string or None")
        if prompt is not None and not isinstance(prompt, str):
            raise TypeError("prompt must be a string or None")
        timeout = float(timeout_seconds) if timeout_seconds is not None else None
        if timeout is not None and timeout < 0:
            raise ValueError("timeout_seconds must be non-negative")

        mode = _derive_sandbox_mode(
            workspace=workspace,
            permissions=permissions,
            explicit=sandbox_mode,
        )
        if mode is SandboxMode.EXTERNAL:
            external = dict(metadata or {}).get("external_sandbox", True)
            metadata = {**dict(metadata or {}), "external_sandbox": external}

        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "agent", agent)
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "messages", _copy_messages(messages))
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "permissions", permissions)
        object.__setattr__(self, "routing", routing)
        object.__setattr__(self, "validators", tuple(validators or ()))
        object.__setattr__(self, "call_args", MappingProxyType(user_call_args(call_args)))
        object.__setattr__(self, "provider_options", _copy_mapping(provider_options))
        object.__setattr__(self, "timeout_seconds", timeout)
        object.__setattr__(self, "metadata", _copy_mapping(metadata))
        object.__setattr__(self, "sandbox_mode", mode)

    def to_agent_request(self) -> AgentRequest:
        request_metadata = {
            "stage": self.stage,
            "agent": _agent_name(self.agent),
            "sandbox_mode": self.sandbox_mode.value,
            "routing": _routing_summary(self.routing),
            "validators": [_validator_summary(validator) for validator in self.validators],
            "call_args": dict(self.call_args),
            "workspace": _workspace_summary(self.workspace),
            "permissions": _permission_summary(
                self.permissions,
                agent=self.agent,
                sandbox_mode=self.sandbox_mode,
            ),
            **dict(self.metadata),
        }
        return AgentRequest(
            prompt=self.prompt,
            messages=self.messages,
            workspace=self.workspace,
            permissions=request_metadata["permissions"],
            timeout_seconds=self.timeout_seconds,
            provider_options=self.provider_options,
            metadata=request_metadata,
        )

    def to_dict(self, *, redact: bool = False) -> dict[str, Any]:
        data = {
            "stage": self.stage,
            "agent": _agent_name(self.agent),
            "prompt": REDACTED_VALUE if redact and self.prompt is not None else self.prompt,
            "messages": [_plain_value(message) for message in self.messages],
            "workspace": _workspace_summary(self.workspace),
            "permissions": _permission_summary(
                self.permissions,
                agent=self.agent,
                sandbox_mode=self.sandbox_mode,
            ),
            "routing": _routing_summary(self.routing),
            "validators": [_validator_summary(validator) for validator in self.validators],
            "call_args": dict(self.call_args),
            "provider_options": dict(self.provider_options),
            "timeout_seconds": self.timeout_seconds,
            "metadata": dict(self.metadata),
            "sandbox_mode": self.sandbox_mode.value,
        }
        return _redact_value(data) if redact else data

    def redacted(self) -> dict[str, Any]:
        return self.to_dict(redact=True)


__all__ = ["DispatchPlan", "SandboxMode"]
