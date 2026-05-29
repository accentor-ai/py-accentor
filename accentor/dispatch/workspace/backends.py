from __future__ import annotations

"""Local staged workspace backend built on real temporary files."""

import hashlib
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from accentor.dispatch.workspace.plans import (
    PathInput,
    PathInputs,
    WorkspaceError,
    WorkspacePathError,
    WorkspacePlan,
    _as_path_items,
    _is_relative_to,
    _normalise_relative_path,
    _rooted_path,
)


class WorkspaceExportError(WorkspaceError):
    """Raised when export tries to copy an undeclared workspace output."""

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        declared: Iterable[str] = (),
    ) -> None:
        super().__init__(message)
        self.path = path
        self.declared = tuple(declared)

    def diagnostic(self) -> dict[str, Any]:
        return {
            "code": "workspace.export_undeclared",
            "message": str(self),
            "severity": "error",
            "source": "workspace",
            "hint": "Declare the file in WorkspacePlan(exportable=...) before exporting it.",
            "details": {
                "path": self.path,
                "declared": list(self.declared),
            },
        }

    def to_diagnostic(self) -> dict[str, Any]:
        return self.diagnostic()

    def to_dict(self) -> dict[str, Any]:
        return self.diagnostic()


@dataclass(frozen=True)
class WorkspaceFileRecord:
    """Metadata for a file currently present in the staged workspace."""

    name: str
    path: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkspaceExportRecord:
    """Metadata for a declared file exported from the staged workspace."""

    name: str
    source_path: str
    destination_path: str
    size_bytes: int
    sha256: str

    @property
    def path(self) -> str:
        return self.destination_path

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = self.destination_path
        return data


@dataclass(frozen=True)
class StagedWorkspace:
    """Handle returned after a local backend prepares a workspace plan."""

    workspace_root: Path
    plan: WorkspacePlan
    staged_files: tuple[str, ...]
    revoked_files: tuple[str, ...]
    backend: "LocalWorkspaceBackend"

    @property
    def root(self) -> Path:
        return self.workspace_root

    def path(self, name: PathInput) -> Path:
        return self.backend.path(name)

    def list_files(self) -> list[str]:
        return self.backend.list_files()

    def list_virtual_files(self) -> list[str]:
        return self.list_files()

    def read_text(self, name: PathInput, *, encoding: str = "utf-8") -> str:
        return self.backend.read_text(name, encoding=encoding)

    def read_virtual_file(self, name: PathInput, *, encoding: str = "utf-8") -> str:
        return self.read_text(name, encoding=encoding)

    def write_text(
        self,
        name: PathInput,
        text: str,
        *,
        encoding: str = "utf-8",
    ) -> WorkspaceFileRecord:
        return self.backend.write_text(name, text, encoding=encoding)

    def write_virtual_file(
        self,
        name: PathInput,
        text: str,
        *,
        encoding: str = "utf-8",
    ) -> WorkspaceFileRecord:
        return self.write_text(name, text, encoding=encoding)

    def export_to(
        self,
        destination_root: PathInput,
        *,
        paths: PathInputs = None,
    ) -> list[WorkspaceExportRecord]:
        return self.backend.export(self.plan, destination_root, paths=paths)

    def export(
        self,
        destination_root: PathInput,
        *,
        paths: PathInputs = None,
    ) -> list[WorkspaceExportRecord]:
        return self.export_to(destination_root, paths=paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_root": str(self.workspace_root),
            "plan": self.plan.to_dict(),
            "staged_files": list(self.staged_files),
            "revoked_files": list(self.revoked_files),
            "files": self.list_files(),
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(root: Path, path: Path) -> WorkspaceFileRecord:
    if not path.is_file():
        raise FileNotFoundError(path)
    resolved = path.resolve(strict=True)
    if not _is_relative_to(resolved, root):
        raise WorkspacePathError(f"workspace path escapes root: {path}")
    return WorkspaceFileRecord(
        name=path.relative_to(root).as_posix(),
        path=str(path),
        size_bytes=path.stat().st_size,
        sha256=_sha256_file(path),
    )


def _remove_tree(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        children = sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True)
        for child in children:
            if child.is_dir() and not child.is_symlink():
                child.rmdir()
            else:
                child.unlink(missing_ok=True)
        path.rmdir()
    else:
        path.unlink(missing_ok=True)


def _is_declared(path: str, declared_paths: Iterable[str]) -> bool:
    return any(path == declared or path.startswith(f"{declared}/") for declared in declared_paths)


class LocalWorkspaceBackend:
    """Prepare and inspect local staged workspaces using only the stdlib."""

    def __init__(
        self,
        workspace_root: PathInput | None = None,
        *,
        staging_root: PathInput | None = None,
    ) -> None:
        if workspace_root is not None and staging_root is not None:
            if Path(workspace_root) != Path(staging_root):
                raise ValueError("workspace_root and staging_root aliases must match")
        root_input = workspace_root if workspace_root is not None else staging_root
        if root_input is None:
            root_path = Path(tempfile.mkdtemp(prefix="accentor-workspace-"))
        else:
            root_path = Path(root_input)
            root_path.mkdir(parents=True, exist_ok=True)
        self._root = root_path.resolve(strict=True)
        if not self._root.is_dir():
            raise NotADirectoryError(f"workspace root is not a directory: {self._root}")

    @property
    def root(self) -> Path:
        return self._root

    @property
    def workspace_root(self) -> Path:
        return self._root

    def path(self, name: PathInput, *, create_parent: bool = False) -> Path:
        normalised = _normalise_relative_path(name)
        return _rooted_path(self._root, normalised, create_parent=create_parent)

    def stage(self, plan: WorkspacePlan) -> StagedWorkspace:
        planned = plan.with_workspace_root(self._root)
        staged: list[str] = []
        for name in planned.staged_paths:
            source = planned.source_path(name)
            if not source.is_file():
                raise FileNotFoundError(source)
            resolved_source = source.resolve(strict=True)
            if not _is_relative_to(resolved_source, planned.root):
                raise WorkspacePathError(f"source path escapes workspace root: {name!r}")
            destination = self.path(name, create_parent=True)
            shutil.copy2(source, destination)
            staged.append(name)

        revoked = self.revoke(planned.revoked)
        return StagedWorkspace(
            workspace_root=self._root,
            plan=planned,
            staged_files=tuple(staged),
            revoked_files=revoked,
            backend=self,
        )

    def prepare(self, plan: WorkspacePlan) -> StagedWorkspace:
        return self.stage(plan)

    def prepare_workspace(self, plan: WorkspacePlan) -> StagedWorkspace:
        return self.stage(plan)

    def seed(self, plan: WorkspacePlan) -> StagedWorkspace:
        return self.stage(plan)

    def seed_files(self, plan: WorkspacePlan) -> StagedWorkspace:
        return self.stage(plan)

    def revoke(self, paths: PathInputs, *, missing_ok: bool = True) -> tuple[str, ...]:
        revoked: list[str] = []
        for item in _as_path_items(paths):
            name = _normalise_relative_path(item, label="revoked path")
            target = self.path(name)
            if target.exists() or target.is_symlink():
                _remove_tree(target)
            elif not missing_ok:
                raise FileNotFoundError(target)
            revoked.append(name)
        return tuple(revoked)

    def list_files(self) -> list[str]:
        files: list[str] = []
        for path in sorted(self._root.rglob("*")):
            if path.is_symlink():
                resolved = path.resolve(strict=True)
                if not _is_relative_to(resolved, self._root):
                    raise WorkspacePathError(f"workspace symlink escapes root: {path}")
            if not path.is_file():
                continue
            files.append(_file_record(self._root, path).name)
        return files

    def list_virtual_files(self) -> list[str]:
        return self.list_files()

    def record(self, name: PathInput) -> WorkspaceFileRecord:
        return _file_record(self._root, self.path(name))

    def read_text(self, name: PathInput, *, encoding: str = "utf-8") -> str:
        path = self.path(name)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path.read_text(encoding=encoding)

    def read_virtual_file(self, name: PathInput, *, encoding: str = "utf-8") -> str:
        return self.read_text(name, encoding=encoding)

    def write_text(
        self,
        name: PathInput,
        text: str,
        *,
        encoding: str = "utf-8",
    ) -> WorkspaceFileRecord:
        path = self.path(name, create_parent=True)
        path.write_text(text, encoding=encoding)
        return _file_record(self._root, path)

    def write_virtual_file(
        self,
        name: PathInput,
        text: str,
        *,
        encoding: str = "utf-8",
    ) -> WorkspaceFileRecord:
        return self.write_text(name, text, encoding=encoding)

    def read_bytes(self, name: PathInput) -> bytes:
        path = self.path(name)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path.read_bytes()

    def write_bytes(self, name: PathInput, data: bytes) -> WorkspaceFileRecord:
        path = self.path(name, create_parent=True)
        path.write_bytes(data)
        return _file_record(self._root, path)

    def export(
        self,
        plan: WorkspacePlan,
        destination_root: PathInput,
        *,
        paths: PathInputs = None,
    ) -> list[WorkspaceExportRecord]:
        declared = tuple(plan.exportable)
        requested = (
            tuple(_normalise_relative_path(path, label="export path") for path in _as_path_items(paths))
            if paths is not None
            else declared
        )

        for name in requested:
            if not _is_declared(name, declared):
                raise WorkspaceExportError(
                    f"workspace export is not declared: {name}",
                    path=name,
                    declared=declared,
                )

        destination_root_path = Path(destination_root)
        destination_root_path.mkdir(parents=True, exist_ok=True)
        destination_root_resolved = destination_root_path.resolve(strict=True)

        records: list[WorkspaceExportRecord] = []
        for name in requested:
            source = self.path(name)
            if source.is_dir() and not source.is_symlink():
                files = [path for path in sorted(source.rglob("*")) if path.is_file()]
            elif source.is_file():
                files = [source]
            else:
                raise FileNotFoundError(source)

            for file_path in files:
                relative_name = file_path.relative_to(self._root).as_posix()
                if not _is_declared(relative_name, declared):
                    raise WorkspaceExportError(
                        f"workspace export is not declared: {relative_name}",
                        path=relative_name,
                        declared=declared,
                    )
                destination = _rooted_path(
                    destination_root_resolved,
                    relative_name,
                    create_parent=True,
                )
                shutil.copy2(file_path, destination)
                stat = destination.stat()
                records.append(
                    WorkspaceExportRecord(
                        name=relative_name,
                        source_path=str(file_path),
                        destination_path=str(destination),
                        size_bytes=stat.st_size,
                        sha256=_sha256_file(destination),
                    )
                )
        return records

    def export_declared(
        self,
        plan: WorkspacePlan,
        destination_root: PathInput,
    ) -> list[WorkspaceExportRecord]:
        return self.export(plan, destination_root)

    def export_outputs(
        self,
        plan: WorkspacePlan,
        destination_root: PathInput,
    ) -> list[WorkspaceExportRecord]:
        return self.export(plan, destination_root)

    def manifest(self) -> dict[str, Any]:
        records = [self.record(name).to_dict() for name in self.list_files()]
        return {
            "workspace_root": str(self._root),
            "file_count": len(records),
            "files": records,
        }


LocalStagingBackend = LocalWorkspaceBackend


__all__ = [
    "LocalStagingBackend",
    "LocalWorkspaceBackend",
    "StagedWorkspace",
    "WorkspaceExportError",
    "WorkspaceExportRecord",
    "WorkspaceFileRecord",
]
