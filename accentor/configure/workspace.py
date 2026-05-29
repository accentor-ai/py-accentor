from __future__ import annotations

"""User-facing workspace intent records and compilers."""

import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping

from accentor.core.task.diagnostics import Diagnostic
from accentor.dispatch.workspace import WorkspacePlan


PathInput = str | os.PathLike[str]
PathInputs = PathInput | Iterable[PathInput] | None


def _as_path_items(value: PathInputs) -> tuple[PathInput, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, os.PathLike)):
        return (value,)
    return tuple(value)


def _dedupe(values: Iterable[PathInput]) -> tuple[PathInput, ...]:
    seen: set[str] = set()
    result: list[PathInput] = []
    for value in values:
        key = os.fspath(value)
        if key not in seen:
            result.append(value)
            seen.add(key)
    return tuple(result)


def _plain_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    if isinstance(value, Diagnostic):
        return value.to_dict()
    return value


def _copy_metadata(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return {str(key): _plain_value(item) for key, item in (value or {}).items()}


def _path_text(path: PathInput) -> str:
    raw = os.fspath(path)
    if isinstance(raw, bytes):
        raise TypeError("workspace paths must be text, not bytes")
    return raw


def _has_glob(path: PathInput) -> bool:
    return any(char in _path_text(path) for char in "*?[")


def _glob_is_safe(pattern: str) -> bool:
    if not pattern or "\x00" in pattern or "\n" in pattern or "\r" in pattern:
        return False
    if "\\" in pattern:
        return False
    posix = PurePosixPath(pattern)
    windows = PureWindowsPath(pattern)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        return False
    return not any(part in ("", ".", "..") for part in pattern.split("/"))


def _expand_globs(
    *,
    root: PathInput | None,
    paths: Iterable[PathInput],
    label: str,
) -> tuple[tuple[PathInput, ...], tuple[Diagnostic, ...]]:
    root_path = Path.cwd().resolve(strict=False) if root is None else Path(root).resolve(strict=False)
    expanded: list[PathInput] = []
    diagnostics: list[Diagnostic] = []

    for path in paths:
        if not _has_glob(path):
            expanded.append(path)
            continue

        pattern = _path_text(path)
        if not _glob_is_safe(pattern):
            diagnostics.append(
                Diagnostic.warning(
                    code="configure.workspace.glob_ignored",
                    message="Workspace glob pattern is unsafe and was ignored.",
                    source="configure.workspace",
                    hint="Use a relative POSIX glob such as 'inputs/*.txt'.",
                    details={"pattern": pattern, "scope": label},
                )
            )
            continue

        matches = sorted(item for item in root_path.glob(pattern) if item.is_file())
        if not matches:
            diagnostics.append(
                Diagnostic.warning(
                    code="configure.workspace.glob_empty",
                    message="Workspace glob pattern did not match any files.",
                    source="configure.workspace",
                    hint="Check the pattern or pass an explicit file path.",
                    details={"pattern": pattern, "scope": label},
                )
            )
            continue
        expanded.extend(matches)

    return _dedupe(expanded), tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class WorkspaceCompilation:
    """Compiled workspace intent plus non-fatal configuration diagnostics."""

    plan: WorkspacePlan
    diagnostics: tuple[Diagnostic, ...] = ()
    intent: "WorkspaceIntent | None" = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def workspace_plan(self) -> WorkspacePlan:
        return self.plan

    @property
    def ok(self) -> bool:
        return not any(diagnostic.severity in {"error", "critical"} for diagnostic in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace": self.plan.to_dict(),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "ok": self.ok,
            "metadata": _plain_value(self.metadata),
        }


@dataclass(frozen=True, slots=True, init=False)
class WorkspaceIntent:
    """Declarative staged-workspace file, edit, output, and revocation intent."""

    root: PathInput | None
    workspace_root: PathInput | None
    readable: tuple[PathInput, ...]
    editable: tuple[PathInput, ...]
    revoked: tuple[PathInput, ...]
    exportable: tuple[PathInput, ...]
    metadata: Mapping[str, Any]

    def __init__(
        self,
        readable: PathInputs = None,
        editable: PathInputs = None,
        *,
        root: PathInput | None = None,
        workspace_root: PathInput | None = None,
        readable_files: PathInputs = None,
        readable_paths: PathInputs = None,
        workspace_files: PathInputs = None,
        editable_files: PathInputs = None,
        editable_paths: PathInputs = None,
        revoked: PathInputs = None,
        revoked_files: PathInputs = None,
        revoke_files: PathInputs = None,
        exportable: PathInputs = None,
        exportable_files: PathInputs = None,
        outputs: PathInputs = None,
        output_files: PathInputs = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        readable_items = (
            *_as_path_items(readable),
            *_as_path_items(readable_files),
            *_as_path_items(readable_paths),
            *_as_path_items(workspace_files),
        )
        editable_items = (
            *_as_path_items(editable),
            *_as_path_items(editable_files),
            *_as_path_items(editable_paths),
        )
        revoked_items = (
            *_as_path_items(revoked),
            *_as_path_items(revoked_files),
            *_as_path_items(revoke_files),
        )
        exportable_items = (
            *_as_path_items(exportable),
            *_as_path_items(exportable_files),
            *_as_path_items(outputs),
            *_as_path_items(output_files),
        )

        object.__setattr__(self, "root", root)
        object.__setattr__(self, "workspace_root", workspace_root)
        object.__setattr__(self, "readable", _dedupe(readable_items))
        object.__setattr__(self, "editable", _dedupe(editable_items))
        object.__setattr__(self, "revoked", _dedupe(revoked_items))
        object.__setattr__(self, "exportable", _dedupe(exportable_items))
        object.__setattr__(self, "metadata", _copy_metadata(metadata))

    @classmethod
    def from_any(
        cls,
        value: "WorkspaceIntent | Mapping[str, Any] | None" = None,
        **overrides: Any,
    ) -> "WorkspaceIntent":
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
        raise TypeError("workspace intent must be WorkspaceIntent, mapping, or None")

    @classmethod
    def empty(cls, *, root: PathInput | None = None) -> "WorkspaceIntent":
        return cls(root=root)

    @property
    def readable_files(self) -> tuple[PathInput, ...]:
        return self.readable

    @property
    def workspace_files(self) -> tuple[PathInput, ...]:
        return self.readable

    @property
    def editable_files(self) -> tuple[PathInput, ...]:
        return self.editable

    @property
    def revoked_files(self) -> tuple[PathInput, ...]:
        return self.revoked

    @property
    def revoke_files(self) -> tuple[PathInput, ...]:
        return self.revoked

    @property
    def exportable_files(self) -> tuple[PathInput, ...]:
        return self.exportable

    @property
    def outputs(self) -> tuple[PathInput, ...]:
        return self.exportable

    def to_intent_kwargs(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "workspace_root": self.workspace_root,
            "readable": self.readable,
            "editable": self.editable,
            "revoked": self.revoked,
            "exportable": self.exportable,
            "metadata": self.metadata,
        }

    def compile_with_diagnostics(self, *, root: PathInput | None = None) -> WorkspaceCompilation:
        return WorkspaceCompiler(root=root).compile_with_diagnostics(self)

    def compile(self, *, root: PathInput | None = None) -> WorkspacePlan:
        return self.compile_with_diagnostics(root=root).plan

    def to_workspace_plan(self, *, root: PathInput | None = None) -> WorkspacePlan:
        return self.compile(root=root)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root) if self.root is not None else None,
            "workspace_root": str(self.workspace_root) if self.workspace_root is not None else None,
            "readable": [_plain_value(path) for path in self.readable],
            "editable": [_plain_value(path) for path in self.editable],
            "revoked": [_plain_value(path) for path in self.revoked],
            "exportable": [_plain_value(path) for path in self.exportable],
            "metadata": _plain_value(self.metadata),
        }


class WorkspaceCompiler:
    """Compile user shorthand workspace declarations into ``WorkspacePlan`` records."""

    def __init__(self, *, root: PathInput | None = None) -> None:
        self.root = root
        self.last_diagnostics: tuple[Diagnostic, ...] = ()

    def compile_with_diagnostics(
        self,
        intent: WorkspaceIntent | Mapping[str, Any] | None = None,
        **shorthands: Any,
    ) -> WorkspaceCompilation:
        workspace_intent = WorkspaceIntent.from_any(intent, **shorthands)
        root = workspace_intent.root if workspace_intent.root is not None else self.root

        readable, readable_diagnostics = _expand_globs(
            root=root,
            paths=workspace_intent.readable,
            label="readable",
        )
        editable, editable_diagnostics = _expand_globs(
            root=root,
            paths=workspace_intent.editable,
            label="editable",
        )
        revoked, revoked_diagnostics = _expand_globs(
            root=root,
            paths=workspace_intent.revoked,
            label="revoked",
        )
        exportable, exportable_diagnostics = _expand_globs(
            root=root,
            paths=workspace_intent.exportable,
            label="exportable",
        )

        plan = WorkspacePlan(
            root=root,
            workspace_root=workspace_intent.workspace_root,
            readable=readable,
            editable=editable,
            revoke_files=revoked,
            outputs=exportable,
            metadata=workspace_intent.metadata,
        )
        diagnostics = (
            *readable_diagnostics,
            *editable_diagnostics,
            *revoked_diagnostics,
            *exportable_diagnostics,
        )
        self.last_diagnostics = diagnostics
        return WorkspaceCompilation(
            plan=plan,
            diagnostics=diagnostics,
            intent=workspace_intent,
            metadata=workspace_intent.metadata,
        )

    def compile(
        self,
        intent: WorkspaceIntent | Mapping[str, Any] | None = None,
        **shorthands: Any,
    ) -> WorkspacePlan:
        return self.compile_with_diagnostics(intent, **shorthands).plan

    def diagnostics_for(
        self,
        intent: WorkspaceIntent | Mapping[str, Any] | None = None,
        **shorthands: Any,
    ) -> tuple[Diagnostic, ...]:
        return self.compile_with_diagnostics(intent, **shorthands).diagnostics


def compile_workspace(
    intent: WorkspaceIntent | Mapping[str, Any] | None = None,
    **shorthands: Any,
) -> WorkspacePlan:
    root = shorthands.pop("root", None)
    return WorkspaceCompiler(root=root).compile(intent, **shorthands)


def compile_workspace_with_diagnostics(
    intent: WorkspaceIntent | Mapping[str, Any] | None = None,
    **shorthands: Any,
) -> WorkspaceCompilation:
    root = shorthands.pop("root", None)
    return WorkspaceCompiler(root=root).compile_with_diagnostics(intent, **shorthands)


__all__ = [
    "WorkspaceCompilation",
    "WorkspaceCompiler",
    "WorkspaceIntent",
    "compile_workspace",
    "compile_workspace_with_diagnostics",
]
