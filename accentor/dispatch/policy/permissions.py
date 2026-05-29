from __future__ import annotations

"""Permission set and provider policy decision records."""

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from accentor.core.task.diagnostics import (
    Diagnostic,
    JsonValue,
    _normalize_json_value,
    _plain_json_value,
)
from accentor.dispatch.agents.base.capabilities import AgentCapabilities
from accentor.dispatch.policy.commands import CommandPolicy
from accentor.dispatch.policy.environment import EnvironmentPolicy
from accentor.dispatch.policy.network import NetworkPolicy
from accentor.dispatch.policy.revisions import GrantRead, PermissionRevision, RevokeRead


_ERROR_SEVERITIES = frozenset({"error", "critical"})


def _string_tuple(values: Iterable[object] | object | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        return (str(values),)
    try:
        return tuple(str(value) for value in values)  # type: ignore[arg-type]
    except TypeError:
        return (str(values),)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return tuple(ordered)


def _normalize_metadata(value: Mapping[str, Any] | None) -> Mapping[str, JsonValue]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    return _normalize_json_value(value)  # type: ignore[return-value]


def _provider_name(provider: str | object | None) -> str:
    if provider is None:
        return "generic"
    if isinstance(provider, str):
        return provider.lower()
    name = getattr(provider, "name", None)
    return str(name if name is not None else type(provider).__name__).lower()


def _normalize_diagnostics(
    diagnostics: Sequence[Diagnostic | Mapping[str, Any]] | None,
) -> tuple[Diagnostic, ...]:
    if diagnostics is None:
        return ()
    normalized: list[Diagnostic] = []
    for diagnostic in diagnostics:
        if isinstance(diagnostic, Diagnostic):
            normalized.append(diagnostic)
        elif isinstance(diagnostic, Mapping):
            normalized.append(Diagnostic(**diagnostic))
        else:
            raise TypeError("diagnostics must contain Diagnostic objects or diagnostic mappings")
    return tuple(normalized)


def _normalize_revision(value: PermissionRevision | Mapping[str, Any]) -> PermissionRevision:
    if isinstance(value, PermissionRevision):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("permission revisions must be PermissionRevision records or mappings")
    action = str(value.get("action", ""))
    paths = value.get("paths")
    kwargs = {
        "phase": value.get("phase"),
        "reason": value.get("reason"),
        "revision_id": value.get("revision_id"),
        "timestamp": value.get("timestamp"),
        "metadata": value.get("metadata"),
    }
    if action == "grant_read":
        return GrantRead(paths, **kwargs)
    if action == "revoke_read":
        return RevokeRead(paths, **kwargs)
    return PermissionRevision(action=action, paths=paths, **kwargs)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Serializable provider policy decision for a compiled permission set."""

    ok: bool
    provider: str | None = None
    sandbox_mode: str | None = None
    provider_flags: Mapping[str, JsonValue] = field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()
    unsupported: tuple[str, ...] = ()
    post_run_checks: tuple[str, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_flags", _normalize_metadata(self.provider_flags))
        object.__setattr__(self, "diagnostics", _normalize_diagnostics(self.diagnostics))
        object.__setattr__(self, "unsupported", tuple(str(item) for item in self.unsupported))
        object.__setattr__(self, "post_run_checks", tuple(str(item) for item in self.post_run_checks))
        object.__setattr__(self, "metadata", _normalize_metadata(self.metadata))

    @property
    def supported(self) -> bool:
        return self.ok and not self.unsupported

    @property
    def is_supported(self) -> bool:
        return self.supported

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "supported": self.supported,
            "provider": self.provider,
            "sandbox_mode": self.sandbox_mode,
            "provider_flags": _plain_json_value(self.provider_flags),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "unsupported": list(self.unsupported),
            "post_run_checks": list(self.post_run_checks),
            "metadata": _plain_json_value(self.metadata),
        }


@dataclass(frozen=True, slots=True, init=False)
class PermissionSet:
    """Compiled dispatch-layer permission record.

    The record captures declared intent, provider flag mapping, and deterministic
    checks Accentor should run after dispatch. It is not a runtime monitor.
    """

    readable: tuple[str, ...]
    editable: tuple[str, ...]
    network: NetworkPolicy
    commands: CommandPolicy
    environment: EnvironmentPolicy
    revisions: tuple[PermissionRevision, ...]
    metadata: Mapping[str, JsonValue]

    def __init__(
        self,
        readable: Iterable[object] | object | None = None,
        editable: Iterable[object] | object | None = None,
        *,
        readable_paths: Iterable[object] | object | None = None,
        editable_paths: Iterable[object] | object | None = None,
        network: NetworkPolicy | Mapping[str, Any] | bool | None = None,
        network_policy: NetworkPolicy | Mapping[str, Any] | bool | None = None,
        command: CommandPolicy | Mapping[str, Any] | bool | None = None,
        commands: CommandPolicy | Mapping[str, Any] | bool | None = None,
        command_policy: CommandPolicy | Mapping[str, Any] | bool | None = None,
        environment: EnvironmentPolicy | Mapping[str, Any] | None = None,
        environment_policy: EnvironmentPolicy | Mapping[str, Any] | None = None,
        revisions: Iterable[PermissionRevision | Mapping[str, Any]] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        readable_value = readable if readable is not None else readable_paths
        editable_value = editable if editable is not None else editable_paths
        network_value = network if network is not None else network_policy
        command_value = commands if commands is not None else command
        if command_value is None:
            command_value = command_policy
        environment_value = environment if environment is not None else environment_policy

        object.__setattr__(self, "readable", _dedupe(_string_tuple(readable_value)))
        object.__setattr__(self, "editable", _dedupe(_string_tuple(editable_value)))
        object.__setattr__(self, "network", NetworkPolicy.from_any(network_value))
        object.__setattr__(self, "commands", CommandPolicy.from_any(command_value))
        object.__setattr__(self, "environment", EnvironmentPolicy.from_any(environment_value))
        object.__setattr__(
            self,
            "revisions",
            tuple(_normalize_revision(revision) for revision in (revisions or ())),
        )
        object.__setattr__(self, "metadata", _normalize_metadata(metadata))

    @property
    def readable_paths(self) -> tuple[str, ...]:
        return self.readable

    @property
    def editable_paths(self) -> tuple[str, ...]:
        return self.editable

    @property
    def has_read_access(self) -> bool:
        return bool(self.readable)

    @property
    def has_write_access(self) -> bool:
        return bool(self.editable)

    def neutral_sandbox_mode(self) -> str:
        return "workspace_write" if self.editable else "read_only"

    def provider_sandbox_mode(self, provider: str | object | None = None) -> str:
        mode = self.neutral_sandbox_mode()
        provider_name = _provider_name(provider)
        if "codex" in provider_name:
            return mode.replace("_", "-")
        return mode

    def sandbox_mode(self, provider: str | object | None = None) -> str:
        return self.provider_sandbox_mode(provider)

    def post_run_checks(self) -> tuple[str, ...]:
        checks: list[str] = []
        if self.readable:
            checks.append("staged_read_scope")
        if self.editable:
            checks.extend(["diff_scope", "export_scope"])
        if self.revisions:
            checks.append("permission_revisions")
        return tuple(checks)

    def provider_flags(self, provider: str | object | None = None) -> dict[str, Any]:
        sandbox_mode = self.provider_sandbox_mode(provider)
        flags: dict[str, Any] = {
            "sandbox": sandbox_mode,
            "sandbox_mode": sandbox_mode,
        }
        flags.update(self.network.provider_flags(provider))
        flags.update(self.commands.provider_flags(provider))
        flags.update(self.environment.provider_flags(provider))
        return flags

    def to_provider_flags(self, provider: str | object | None = None) -> dict[str, Any]:
        return self.provider_flags(provider)

    def unsupported_diagnostics(
        self,
        provider: str | object | None = None,
        *,
        capabilities: AgentCapabilities | Mapping[str, Any] | object | None = None,
    ) -> tuple[Diagnostic, ...]:
        provider_name = _provider_name(provider)
        diagnostics: list[Diagnostic] = []
        capability_snapshot = AgentCapabilities.from_any(capabilities) if capabilities is not None else None

        if capability_snapshot is not None:
            if (self.readable or self.editable) and not capability_snapshot.supports_files:
                diagnostics.append(
                    Diagnostic.error(
                        code="policy.files.provider_unsupported",
                        message="The selected provider does not advertise file workspace support.",
                        source="dispatch.policy.permissions",
                        hint="Choose a file-capable provider or remove readable/editable paths.",
                        details={"provider": provider_name},
                    )
                )
            if self.editable and not capability_snapshot.supports_sandbox:
                diagnostics.append(
                    Diagnostic.error(
                        code="policy.sandbox.provider_unsupported",
                        message="Editable paths require a provider with sandbox support in Accentor v1.",
                        source="dispatch.policy.permissions",
                        hint="Choose a sandbox-capable provider or remove editable paths.",
                        details={"provider": provider_name, "sandbox_mode": self.provider_sandbox_mode(provider)},
                    )
                )

        diagnostics.extend(self.network.unsupported_diagnostics(provider))
        diagnostics.extend(self.commands.unsupported_diagnostics(provider, capabilities=capabilities))
        diagnostics.extend(self.environment.unsupported_diagnostics(provider))
        return tuple(diagnostics)

    def evaluate(
        self,
        provider: str | object | None = None,
        *,
        capabilities: AgentCapabilities | Mapping[str, Any] | object | None = None,
        diagnostics: Sequence[Diagnostic | Mapping[str, Any]] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> PolicyDecision:
        provider_name = _provider_name(provider)
        all_diagnostics = [
            *_normalize_diagnostics(diagnostics),
            *self.unsupported_diagnostics(provider, capabilities=capabilities),
        ]
        unsupported = tuple(
            diagnostic.code
            for diagnostic in all_diagnostics
            if "unsupported" in diagnostic.code
        )
        ok = not any(diagnostic.severity in _ERROR_SEVERITIES for diagnostic in all_diagnostics)
        return PolicyDecision(
            ok=ok,
            provider=provider_name,
            sandbox_mode=self.provider_sandbox_mode(provider),
            provider_flags=self.provider_flags(provider),
            diagnostics=tuple(all_diagnostics),
            unsupported=unsupported,
            post_run_checks=self.post_run_checks(),
            metadata=metadata or {},
        )

    def to_policy_decision(
        self,
        provider: str | object | None = None,
        *,
        capabilities: AgentCapabilities | Mapping[str, Any] | object | None = None,
    ) -> PolicyDecision:
        return self.evaluate(provider, capabilities=capabilities)

    def provider_decision(
        self,
        provider: str | object | None = None,
        *,
        capabilities: AgentCapabilities | Mapping[str, Any] | object | None = None,
    ) -> PolicyDecision:
        return self.evaluate(provider, capabilities=capabilities)

    def with_revision(self, revision: PermissionRevision | Mapping[str, Any]) -> "PermissionSet":
        normalized_revision = _normalize_revision(revision)
        readable = list(self.readable)
        if normalized_revision.action == "grant_read":
            readable = list(_dedupe((*readable, *normalized_revision.paths)))
        elif normalized_revision.action == "revoke_read":
            revoked = set(normalized_revision.paths)
            readable = [path for path in readable if path not in revoked]

        return PermissionSet(
            readable=readable,
            editable=self.editable,
            network=self.network,
            commands=self.commands,
            environment=self.environment,
            revisions=(*self.revisions, normalized_revision),
            metadata=self.metadata,
        )

    def grant_read(
        self,
        paths: Iterable[object] | object,
        *,
        phase: str | None = None,
        reason: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "PermissionSet":
        return self.with_revision(GrantRead(paths, phase=phase, reason=reason, metadata=metadata))

    def revoke_read(
        self,
        paths: Iterable[object] | object,
        *,
        phase: str | None = None,
        reason: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "PermissionSet":
        return self.with_revision(RevokeRead(paths, phase=phase, reason=reason, metadata=metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "readable": list(self.readable),
            "editable": list(self.editable),
            "network": self.network.to_dict(),
            "commands": self.commands.to_dict(),
            "environment": self.environment.to_dict(),
            "revisions": [revision.to_dict() for revision in self.revisions],
            "metadata": _plain_json_value(self.metadata),
        }


__all__ = ["PermissionSet", "PolicyDecision"]
