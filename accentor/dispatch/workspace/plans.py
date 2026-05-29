from __future__ import annotations

"""Workspace planning records for local staged workspaces."""

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping


PathInput = str | os.PathLike[str]
PathInputs = PathInput | Iterable[PathInput] | None


class WorkspaceError(ValueError):
    """Base class for workspace planning and staging errors."""


class WorkspacePathError(WorkspaceError):
    """Raised when a workspace path is unsafe or escapes its declared root."""


def _plain_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    return value


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _reject_bad_path_text(raw: str, *, label: str = "workspace path") -> None:
    if not raw:
        raise WorkspacePathError(f"{label} must not be empty")
    if "\x00" in raw:
        raise WorkspacePathError(f"{label} must not contain NUL bytes: {raw!r}")
    if "\n" in raw or "\r" in raw:
        raise WorkspacePathError(f"{label} must not contain newlines: {raw!r}")


def _normalise_relative_path(path: PathInput, *, label: str = "workspace path") -> str:
    """Return a strict POSIX relative path suitable for staged workspaces."""

    raw = os.fspath(path)
    _reject_bad_path_text(raw, label=label)

    if "\\" in raw:
        raise WorkspacePathError(f"backslash path separators are not allowed: {raw!r}")

    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise WorkspacePathError(f"absolute {label}s are not allowed: {raw!r}")

    parts = raw.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise WorkspacePathError(f"path traversal is not allowed: {raw!r}")

    return "/".join(parts)


def _rooted_path(root: Path, relative_path: str, *, create_parent: bool = False) -> Path:
    normalised = _normalise_relative_path(relative_path)
    candidate = root.joinpath(*PurePosixPath(normalised).parts)
    parent = candidate.parent

    probe = candidate if candidate.exists() or candidate.is_symlink() else parent
    while not probe.exists() and probe != root and probe.parent != probe:
        probe = probe.parent

    if probe.exists() or probe.is_symlink():
        try:
            resolved_probe = probe.resolve(strict=True)
        except OSError as exc:
            raise WorkspacePathError(f"workspace path cannot be resolved: {normalised!r}") from exc
        if not _is_relative_to(resolved_probe, root):
            raise WorkspacePathError(f"workspace path escapes root: {normalised!r}")

    if create_parent:
        parent.mkdir(parents=True, exist_ok=True)

    if candidate.exists() or candidate.is_symlink():
        try:
            resolved_candidate = candidate.resolve(strict=True)
        except OSError as exc:
            raise WorkspacePathError(f"workspace path cannot be resolved: {normalised!r}") from exc
        if not _is_relative_to(resolved_candidate, root):
            raise WorkspacePathError(f"workspace path escapes root: {normalised!r}")
    elif parent.exists() or parent.is_symlink():
        try:
            resolved_parent = parent.resolve(strict=True)
        except OSError as exc:
            raise WorkspacePathError(f"workspace path cannot be resolved: {normalised!r}") from exc
        if not _is_relative_to(resolved_parent, root):
            raise WorkspacePathError(f"workspace path escapes root: {normalised!r}")

    return candidate


def _normalise_plan_path(root: Path, path: PathInput, *, label: str = "workspace path") -> str:
    raw = os.fspath(path)
    _reject_bad_path_text(raw, label=label)

    windows = PureWindowsPath(raw)
    if Path(raw).is_absolute() or windows.is_absolute() or windows.drive:
        resolved = Path(raw).resolve(strict=False)
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise WorkspacePathError(f"{label} escapes workspace root: {raw!r}") from exc
        normalised = _normalise_relative_path(relative.as_posix(), label=label)
    else:
        normalised = _normalise_relative_path(raw, label=label)

    _rooted_path(root, normalised)
    return normalised


def _as_path_items(value: PathInputs) -> tuple[PathInput, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, os.PathLike)):
        return (value,)
    return tuple(value)


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return tuple(result)


def _normalise_many(root: Path, paths: Iterable[PathInput], *, label: str) -> tuple[str, ...]:
    return _dedupe(_normalise_plan_path(root, path, label=label) for path in paths)


def _is_same_or_child(path: str, declared: str) -> bool:
    return path == declared or path.startswith(f"{declared}/")


@dataclass(frozen=True, slots=True, init=False)
class WorkspacePlan:
    """Provider-neutral record describing one local staged workspace."""

    root: Path
    workspace_root: Path | None
    readable: tuple[str, ...]
    editable: tuple[str, ...]
    revoked: tuple[str, ...]
    exportable: tuple[str, ...]
    metadata: Mapping[str, Any]

    def __init__(
        self,
        root: PathInput | None = None,
        *,
        workspace_root: PathInput | None = None,
        readable: PathInputs = None,
        editable: PathInputs = None,
        revoked: PathInputs = None,
        exportable: PathInputs = None,
        readable_files: PathInputs = None,
        workspace_files: PathInputs = None,
        editable_files: PathInputs = None,
        revoked_files: PathInputs = None,
        revoke_files: PathInputs = None,
        exportable_files: PathInputs = None,
        outputs: PathInputs = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        resolved_root = Path.cwd().resolve(strict=False) if root is None else Path(root).resolve(strict=False)
        if not resolved_root.is_absolute():
            resolved_root = resolved_root.resolve(strict=False)

        readable_items = (
            *_as_path_items(readable),
            *_as_path_items(readable_files),
            *_as_path_items(workspace_files),
        )
        editable_items = (*_as_path_items(editable), *_as_path_items(editable_files))
        revoked_items = (
            *_as_path_items(revoked),
            *_as_path_items(revoked_files),
            *_as_path_items(revoke_files),
        )
        exportable_items = (
            *_as_path_items(exportable),
            *_as_path_items(exportable_files),
            *_as_path_items(outputs),
        )

        object.__setattr__(self, "root", resolved_root)
        object.__setattr__(
            self,
            "workspace_root",
            Path(workspace_root).resolve(strict=False) if workspace_root is not None else None,
        )
        object.__setattr__(
            self,
            "readable",
            _normalise_many(resolved_root, readable_items, label="readable path"),
        )
        object.__setattr__(
            self,
            "editable",
            _normalise_many(resolved_root, editable_items, label="editable path"),
        )
        object.__setattr__(
            self,
            "revoked",
            _normalise_many(resolved_root, revoked_items, label="revoked path"),
        )
        object.__setattr__(
            self,
            "exportable",
            _normalise_many(resolved_root, exportable_items, label="exportable path"),
        )
        object.__setattr__(self, "metadata", dict(metadata or {}))

    @classmethod
    def empty(cls, root: PathInput | None = None) -> "WorkspacePlan":
        return cls(root=root)

    @classmethod
    def from_files(
        cls,
        files: PathInputs = None,
        *,
        root: PathInput | None = None,
        editable: PathInputs = None,
        revoke_files: PathInputs = None,
        outputs: PathInputs = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "WorkspacePlan":
        return cls(
            root=root,
            readable=files,
            editable=editable,
            revoke_files=revoke_files,
            outputs=outputs,
            metadata=metadata,
        )

    @property
    def readable_paths(self) -> tuple[str, ...]:
        return self.readable

    @property
    def readable_files(self) -> tuple[str, ...]:
        return self.readable

    @property
    def workspace_files(self) -> tuple[str, ...]:
        return self.readable

    @property
    def editable_paths(self) -> tuple[str, ...]:
        return self.editable

    @property
    def editable_files(self) -> tuple[str, ...]:
        return self.editable

    @property
    def revoked_paths(self) -> tuple[str, ...]:
        return self.revoked

    @property
    def revoked_files(self) -> tuple[str, ...]:
        return self.revoked

    @property
    def revoke_files(self) -> tuple[str, ...]:
        return self.revoked

    @property
    def exportable_paths(self) -> tuple[str, ...]:
        return self.exportable

    @property
    def exportable_files(self) -> tuple[str, ...]:
        return self.exportable

    @property
    def outputs(self) -> tuple[str, ...]:
        return self.exportable

    @property
    def staged_paths(self) -> tuple[str, ...]:
        declared = _dedupe((*self.readable, *self.editable))
        return tuple(
            path
            for path in declared
            if not any(_is_same_or_child(path, revoked) for revoked in self.revoked)
        )

    def source_path(self, path: PathInput) -> Path:
        normalised = _normalise_plan_path(self.root, path, label="workspace path")
        return _rooted_path(self.root, normalised)

    def is_export_declared(self, path: PathInput) -> bool:
        normalised = _normalise_relative_path(path, label="export path")
        return any(_is_same_or_child(normalised, declared) for declared in self.exportable)

    def with_workspace_root(self, workspace_root: PathInput) -> "WorkspacePlan":
        return WorkspacePlan(
            root=self.root,
            workspace_root=workspace_root,
            readable=self.readable,
            editable=self.editable,
            revoked=self.revoked,
            exportable=self.exportable,
            metadata=self.metadata,
        )

    def with_revoked(self, paths: PathInputs) -> "WorkspacePlan":
        return WorkspacePlan(
            root=self.root,
            workspace_root=self.workspace_root,
            readable=self.readable,
            editable=self.editable,
            revoked=(*self.revoked, *_as_path_items(paths)),
            exportable=self.exportable,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "workspace_root": str(self.workspace_root) if self.workspace_root is not None else None,
            "readable": list(self.readable),
            "editable": list(self.editable),
            "revoked": list(self.revoked),
            "exportable": list(self.exportable),
            "staged": list(self.staged_paths),
            "metadata": _plain_value(self.metadata),
        }

    def summary(self) -> dict[str, Any]:
        data = self.to_dict()
        data["counts"] = {
            "readable": len(self.readable),
            "editable": len(self.editable),
            "revoked": len(self.revoked),
            "exportable": len(self.exportable),
            "staged": len(self.staged_paths),
        }
        return data


__all__ = [
    "WorkspaceError",
    "WorkspacePathError",
    "WorkspacePlan",
]
