from __future__ import annotations

"""User-facing permission intent records and compilers."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from accentor.core.task.diagnostics import Diagnostic
from accentor.dispatch.policy import (
    CommandPolicy,
    EnvironmentPolicy,
    NetworkPolicy,
    PermissionRevision,
    PermissionSet,
    RevokeRead,
)
from accentor.dispatch.workspace import WorkspacePlan


PathInput = str | os.PathLike[str]
PathInputs = PathInput | Iterable[PathInput] | None


def _as_path_items(value: PathInputs) -> tuple[PathInput, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, os.PathLike)):
        return (value,)
    return tuple(value)


def _is_same_or_child(path: str, declared: str) -> bool:
    return path == declared or path.startswith(f"{declared}/")


def _plain_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    if isinstance(value, PermissionRevision):
        return value.to_dict()
    if isinstance(value, Diagnostic):
        return value.to_dict()
    return value


def _copy_metadata(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return {str(key): _plain_value(item) for key, item in (value or {}).items()}


def _normalise_permission_paths(
    *,
    root: PathInput | None,
    readable: tuple[PathInput, ...],
    editable: tuple[PathInput, ...],
    revoked: tuple[PathInput, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    plan = WorkspacePlan(root=root, readable=readable, editable=editable, revoke_files=revoked)
    revoked_set = plan.revoked
    readable_paths = tuple(
        path for path in plan.readable if not any(_is_same_or_child(path, revoked) for revoked in revoked_set)
    )
    editable_paths = tuple(
        path for path in plan.editable if not any(_is_same_or_child(path, revoked) for revoked in revoked_set)
    )
    return readable_paths, editable_paths, plan.revoked


@dataclass(frozen=True, slots=True)
class PermissionCompilation:
    """Compiled permission intent plus non-fatal configuration diagnostics."""

    permissions: PermissionSet
    diagnostics: tuple[Diagnostic, ...] = ()
    intent: "PermissionIntent | None" = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def permission_set(self) -> PermissionSet:
        return self.permissions

    @property
    def ok(self) -> bool:
        return not any(diagnostic.severity in {"error", "critical"} for diagnostic in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "permissions": self.permissions.to_dict(),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "ok": self.ok,
            "metadata": _plain_value(self.metadata),
        }


@dataclass(frozen=True, slots=True, init=False)
class PermissionIntent:
    """Declarative file, write, network, command, and environment permission intent."""

    root: PathInput | None
    readable: tuple[PathInput, ...]
    editable: tuple[PathInput, ...]
    revoke_files: tuple[PathInput, ...]
    network: NetworkPolicy | Mapping[str, Any] | bool | None
    commands: CommandPolicy | Mapping[str, Any] | bool | None
    environment: EnvironmentPolicy | Mapping[str, Any] | None
    revisions: tuple[PermissionRevision | Mapping[str, Any], ...]
    repair: bool
    metadata: Mapping[str, Any]

    def __init__(
        self,
        readable: PathInputs = None,
        editable: PathInputs = None,
        *,
        root: PathInput | None = None,
        readable_paths: PathInputs = None,
        readable_files: PathInputs = None,
        workspace_files: PathInputs = None,
        editable_paths: PathInputs = None,
        editable_files: PathInputs = None,
        revoke_files: PathInputs = None,
        revoked_files: PathInputs = None,
        revoked: PathInputs = None,
        network: NetworkPolicy | Mapping[str, Any] | bool | None = None,
        network_policy: NetworkPolicy | Mapping[str, Any] | bool | None = None,
        allow_network: bool | None = None,
        search: bool | None = None,
        commands: CommandPolicy | Mapping[str, Any] | bool | None = None,
        command: CommandPolicy | Mapping[str, Any] | bool | None = None,
        command_policy: CommandPolicy | Mapping[str, Any] | bool | None = None,
        allow_shell: bool | None = None,
        environment: EnvironmentPolicy | Mapping[str, Any] | None = None,
        environment_policy: EnvironmentPolicy | Mapping[str, Any] | None = None,
        revisions: Sequence[PermissionRevision | Mapping[str, Any]] | None = None,
        repair: bool | Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        readable_items = (
            *_as_path_items(readable),
            *_as_path_items(readable_paths),
            *_as_path_items(readable_files),
            *_as_path_items(workspace_files),
        )
        editable_items = (
            *_as_path_items(editable),
            *_as_path_items(editable_paths),
            *_as_path_items(editable_files),
        )
        revoked_items = (
            *_as_path_items(revoked),
            *_as_path_items(revoked_files),
            *_as_path_items(revoke_files),
        )

        network_value: NetworkPolicy | Mapping[str, Any] | bool | None = network
        if network_value is None:
            network_value = network_policy
        if search is not None:
            if isinstance(network_value, Mapping):
                network_value = {**network_value, "search": search}
            elif isinstance(network_value, NetworkPolicy):
                network_value = NetworkPolicy(
                    enabled=network_value.enabled,
                    search=search,
                    allowed_hosts=network_value.allowed_hosts,
                    denied_hosts=network_value.denied_hosts,
                )
            else:
                enabled = network_value if network_value is not None else bool(allow_network)
                network_value = NetworkPolicy(enabled=enabled, search=search)
        elif allow_network is not None and network_value is None:
            network_value = allow_network

        command_value: CommandPolicy | Mapping[str, Any] | bool | None = commands
        if command_value is None:
            command_value = command
        if command_value is None:
            command_value = command_policy
        if allow_shell is not None and command_value is None:
            command_value = allow_shell

        environment_value = environment if environment is not None else environment_policy

        object.__setattr__(self, "root", root)
        object.__setattr__(self, "readable", readable_items)
        object.__setattr__(self, "editable", editable_items)
        object.__setattr__(self, "revoke_files", revoked_items)
        object.__setattr__(self, "network", network_value)
        object.__setattr__(self, "commands", command_value)
        object.__setattr__(self, "environment", environment_value)
        object.__setattr__(self, "revisions", tuple(revisions or ()))
        object.__setattr__(self, "repair", repair is not None and repair is not False)
        object.__setattr__(self, "metadata", _copy_metadata(metadata))

    @classmethod
    def from_any(
        cls,
        value: "PermissionIntent | Mapping[str, Any] | None" = None,
        **overrides: Any,
    ) -> "PermissionIntent":
        if value is None:
            return cls(**overrides)
        if isinstance(value, cls):
            if not overrides:
                return value
            data = value.to_intent_kwargs()
            data.update(overrides)
            return cls(**data)
        if isinstance(value, Mapping):
            data = dict(value)
            data.update(overrides)
            return cls(**data)
        raise TypeError("permission intent must be PermissionIntent, mapping, or None")

    @property
    def readable_paths(self) -> tuple[PathInput, ...]:
        return self.readable

    @property
    def editable_paths(self) -> tuple[PathInput, ...]:
        return self.editable

    @property
    def revoked_files(self) -> tuple[PathInput, ...]:
        return self.revoke_files

    def to_intent_kwargs(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "readable": self.readable,
            "editable": self.editable,
            "revoke_files": self.revoke_files,
            "network": self.network,
            "commands": self.commands,
            "environment": self.environment,
            "revisions": self.revisions,
            "repair": self.repair,
            "metadata": self.metadata,
        }

    def diagnostics(self) -> tuple[Diagnostic, ...]:
        diagnostics: list[Diagnostic] = []
        if self.repair and not self.editable:
            diagnostics.append(
                Diagnostic.warning(
                    code="configure.permissions.repair_editable_missing",
                    message="Repair permission intent does not declare editable files.",
                    source="configure.permissions",
                    hint="Declare editable=[...] for any files the repair agent may modify.",
                )
            )
        if self.repair and not self.readable and not self.editable:
            diagnostics.append(
                Diagnostic.warning(
                    code="configure.permissions.repair_scope_missing",
                    message="Repair permission intent does not declare file scope.",
                    source="configure.permissions",
                    hint="Declare readable=[...] and editable=[...] for scoped repair.",
                )
            )
        return tuple(diagnostics)

    def compile_with_diagnostics(self, *, root: PathInput | None = None) -> PermissionCompilation:
        return PermissionCompiler(root=root).compile_with_diagnostics(self)

    def compile(self, *, root: PathInput | None = None) -> PermissionSet:
        return self.compile_with_diagnostics(root=root).permissions

    def to_permission_set(self, *, root: PathInput | None = None) -> PermissionSet:
        return self.compile(root=root)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root) if self.root is not None else None,
            "readable": [_plain_value(path) for path in self.readable],
            "editable": [_plain_value(path) for path in self.editable],
            "revoke_files": [_plain_value(path) for path in self.revoke_files],
            "network": NetworkPolicy.from_any(self.network).to_dict(),
            "commands": CommandPolicy.from_any(self.commands).to_dict(),
            "environment": EnvironmentPolicy.from_any(self.environment).to_dict(),
            "revisions": [_plain_value(revision) for revision in self.revisions],
            "repair": self.repair,
            "metadata": _plain_value(self.metadata),
        }


class PermissionCompiler:
    """Compile user shorthand permission declarations into ``PermissionSet`` records."""

    def __init__(self, *, root: PathInput | None = None) -> None:
        self.root = root
        self.last_diagnostics: tuple[Diagnostic, ...] = ()

    def compile_with_diagnostics(
        self,
        intent: PermissionIntent | Mapping[str, Any] | None = None,
        **shorthands: Any,
    ) -> PermissionCompilation:
        permission_intent = PermissionIntent.from_any(intent, **shorthands)
        root = permission_intent.root if permission_intent.root is not None else self.root
        readable, editable, revoked = _normalise_permission_paths(
            root=root,
            readable=permission_intent.readable,
            editable=permission_intent.editable,
            revoked=permission_intent.revoke_files,
        )
        revisions: list[PermissionRevision | Mapping[str, Any]] = list(permission_intent.revisions)
        if revoked:
            revisions.append(
                RevokeRead(
                    revoked,
                    reason="Files declared in revoke_files are removed before this scope is used.",
                )
            )

        permissions = PermissionSet(
            readable=readable,
            editable=editable,
            network=NetworkPolicy.from_any(permission_intent.network),
            commands=CommandPolicy.from_any(permission_intent.commands),
            environment=EnvironmentPolicy.from_any(permission_intent.environment),
            revisions=revisions,
            metadata=permission_intent.metadata,
        )
        diagnostics = permission_intent.diagnostics()
        self.last_diagnostics = diagnostics
        return PermissionCompilation(
            permissions=permissions,
            diagnostics=diagnostics,
            intent=permission_intent,
            metadata=permission_intent.metadata,
        )

    def compile(
        self,
        intent: PermissionIntent | Mapping[str, Any] | None = None,
        **shorthands: Any,
    ) -> PermissionSet:
        return self.compile_with_diagnostics(intent, **shorthands).permissions

    def diagnostics_for(
        self,
        intent: PermissionIntent | Mapping[str, Any] | None = None,
        **shorthands: Any,
    ) -> tuple[Diagnostic, ...]:
        return self.compile_with_diagnostics(intent, **shorthands).diagnostics


def compile_permissions(
    intent: PermissionIntent | Mapping[str, Any] | None = None,
    **shorthands: Any,
) -> PermissionSet:
    root = shorthands.pop("root", None)
    return PermissionCompiler(root=root).compile(intent, **shorthands)


def compile_permissions_with_diagnostics(
    intent: PermissionIntent | Mapping[str, Any] | None = None,
    **shorthands: Any,
) -> PermissionCompilation:
    root = shorthands.pop("root", None)
    return PermissionCompiler(root=root).compile_with_diagnostics(intent, **shorthands)


__all__ = [
    "PermissionCompilation",
    "PermissionCompiler",
    "PermissionIntent",
    "compile_permissions",
    "compile_permissions_with_diagnostics",
]
