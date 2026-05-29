from __future__ import annotations

"""Workspace diff-scope verdicts for repair workflows.

V1 intentionally answers one narrow question: did the changed files stay inside
the declared editable paths? Patch text is best-effort and intended for human
inspection artifacts, not semantic review.
"""

import difflib
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Literal

from accentor.record.artifacts import ArtifactStore


ChangeStatus = Literal["added", "modified", "deleted"]


class DiffScopeError(ValueError):
    """Raised when diff-scope inputs are not root-confined workspace paths."""


@dataclass(frozen=True, slots=True)
class FileChange:
    """A single file-level workspace change."""

    path: str
    status: ChangeStatus
    inside_editable_scope: bool
    before_sha256: str | None = None
    after_sha256: str | None = None
    before_size_bytes: int | None = None
    after_size_bytes: int | None = None
    kind: str = "file"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "status": self.status,
            "inside_editable_scope": self.inside_editable_scope,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "before_size_bytes": self.before_size_bytes,
            "after_size_bytes": self.after_size_bytes,
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class DiffScopeVerdict:
    """JSON-stable verdict suitable for ``diff_scope_verdict.json``."""

    ok: bool
    editable_paths: tuple[str, ...]
    changed_paths: tuple[str, ...]
    violating_paths: tuple[str, ...]
    added_paths: tuple[str, ...]
    modified_paths: tuple[str, ...]
    deleted_paths: tuple[str, ...]
    changes: tuple[FileChange, ...]
    patch_available: bool = False
    patch_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "editable_paths": list(self.editable_paths),
            "changed_paths": list(self.changed_paths),
            "violating_paths": list(self.violating_paths),
            "added_paths": list(self.added_paths),
            "modified_paths": list(self.modified_paths),
            "deleted_paths": list(self.deleted_paths),
            "changes": [change.to_dict() for change in self.changes],
            "patch_available": self.patch_available,
            "patch_notes": list(self.patch_notes),
        }

    def to_json(self, *, indent: int | None = 2, sort_keys: bool = True) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, indent=indent, sort_keys=sort_keys)


@dataclass(frozen=True, slots=True)
class DiffScopeReport:
    """Diff-scope verdict plus the separate best-effort patch artifact text."""

    verdict: DiffScopeVerdict
    patch_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.to_dict(),
            "patch_text": self.patch_text,
        }


@dataclass(frozen=True, slots=True)
class _Fingerprint:
    sha256: str
    size_bytes: int
    kind: str


@dataclass(frozen=True, slots=True)
class _EditableScope:
    path: str
    is_dir: bool


def diff_workspaces(
    before_root: str | os.PathLike[str],
    after_root: str | os.PathLike[str],
    *,
    editable: Iterable[str | os.PathLike[str]],
) -> DiffScopeReport:
    """Compare two workspace trees and evaluate changed files against scope.

    ``before_root`` is the baseline workspace tree. ``after_root`` is the tree
    after the repair attempt. ``editable`` entries may be relative workspace
    paths, or absolute paths under either root.
    """

    before = _require_directory(before_root, "before_root")
    after = _require_directory(after_root, "after_root")
    scopes = _normalise_editable_scopes(editable, before, after)
    changes = _collect_changes(before, after, scopes)
    patch_text, patch_notes = _build_patch_text_with_notes(before, after, changes=changes)

    changed_paths = tuple(change.path for change in changes)
    violating_paths = tuple(change.path for change in changes if not change.inside_editable_scope)
    added_paths = tuple(change.path for change in changes if change.status == "added")
    modified_paths = tuple(change.path for change in changes if change.status == "modified")
    deleted_paths = tuple(change.path for change in changes if change.status == "deleted")

    verdict = DiffScopeVerdict(
        ok=not violating_paths,
        editable_paths=tuple(scope.path for scope in scopes),
        changed_paths=changed_paths,
        violating_paths=violating_paths,
        added_paths=added_paths,
        modified_paths=modified_paths,
        deleted_paths=deleted_paths,
        changes=tuple(changes),
        patch_available=bool(patch_text),
        patch_notes=tuple(patch_notes),
    )
    return DiffScopeReport(verdict=verdict, patch_text=patch_text)


def evaluate_diff_scope(
    before_root: str | os.PathLike[str],
    after_root: str | os.PathLike[str],
    *,
    editable: Iterable[str | os.PathLike[str]],
) -> DiffScopeVerdict:
    """Return only the JSON-stable diff-scope verdict."""

    return diff_workspaces(before_root, after_root, editable=editable).verdict


def build_patch_text(
    before_root: str | os.PathLike[str],
    after_root: str | os.PathLike[str],
    *,
    changes: Iterable[FileChange] | None = None,
) -> str:
    """Build a best-effort unified diff for text file changes.

    Binary, symlink, and otherwise unsupported changes are represented with a
    short note instead of failing the verdict calculation.
    """

    patch_text, _ = _build_patch_text_with_notes(before_root, after_root, changes=changes)
    return patch_text


def _build_patch_text_with_notes(
    before_root: str | os.PathLike[str],
    after_root: str | os.PathLike[str],
    *,
    changes: Iterable[FileChange] | None = None,
) -> tuple[str, tuple[str, ...]]:
    before = _require_directory(before_root, "before_root")
    after = _require_directory(after_root, "after_root")
    file_changes = tuple(changes) if changes is not None else tuple(_collect_changes(before, after, ()))

    chunks: list[str] = []
    notes: list[str] = []
    for change in file_changes:
        if change.kind != "file":
            note = f"patch omitted for unsupported {change.kind}: {change.path}"
            chunks.append(f"# {note}\n")
            notes.append(note)
            continue

        before_bytes = b"" if change.status == "added" else _read_change_bytes(before, change.path)
        after_bytes = b"" if change.status == "deleted" else _read_change_bytes(after, change.path)
        try:
            before_text = before_bytes.decode("utf-8")
            after_text = after_bytes.decode("utf-8")
        except UnicodeDecodeError:
            note = f"binary or non-utf8 diff omitted: {change.path}"
            chunks.append(f"Binary files a/{change.path} and b/{change.path} differ\n")
            notes.append(note)
            continue

        diff_lines = difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=f"a/{change.path}",
            tofile=f"b/{change.path}",
        )
        chunks.append("".join(diff_lines))

    return "".join(chunks), tuple(notes)


def write_diff_scope_artifacts(
    store: ArtifactStore | str | os.PathLike[str],
    before_root: str | os.PathLike[str],
    after_root: str | os.PathLike[str],
    *,
    editable: Iterable[str | os.PathLike[str]],
    verdict_name: str | os.PathLike[str] = "diff_scope_verdict.json",
    patch_name: str | os.PathLike[str] = "proposed_diff.patch",
) -> DiffScopeReport:
    """Write standard repair diff artifacts and return the computed report."""

    artifact_store = store if isinstance(store, ArtifactStore) else ArtifactStore(store)
    report = diff_workspaces(before_root, after_root, editable=editable)
    artifact_store.write_text(patch_name, report.patch_text, content_type="text/x-patch")
    artifact_store.write_json(verdict_name, report.verdict.to_dict())
    return report


def _require_directory(path: str | os.PathLike[str], label: str) -> Path:
    candidate = Path(path)
    if not candidate.exists():
        raise FileNotFoundError(f"{label} does not exist: {candidate}")
    if not candidate.is_dir():
        raise NotADirectoryError(f"{label} is not a directory: {candidate}")
    return candidate.resolve(strict=True)


def _normalise_editable_scopes(
    editable: Iterable[str | os.PathLike[str]],
    before_root: Path,
    after_root: Path,
) -> tuple[_EditableScope, ...]:
    scopes: dict[str, _EditableScope] = {}
    for item in editable:
        path = _normalise_declared_path(item, before_root, after_root)
        before_path = before_root if path == "." else before_root.joinpath(*PurePosixPath(path).parts)
        after_path = after_root if path == "." else after_root.joinpath(*PurePosixPath(path).parts)
        is_dir = path == "." or before_path.is_dir() or after_path.is_dir()
        scopes[path] = _EditableScope(path=path, is_dir=is_dir)
    return tuple(scopes[path] for path in sorted(scopes))


def _normalise_declared_path(item: str | os.PathLike[str], before_root: Path, after_root: Path) -> str:
    raw = os.fspath(item)
    if not raw:
        raise DiffScopeError("editable path must not be empty")
    if "\x00" in raw:
        raise DiffScopeError("editable path must not contain NUL bytes")
    if "\\" in raw:
        raise DiffScopeError(f"backslash path separators are not allowed: {raw!r}")

    windows = PureWindowsPath(raw)
    if windows.drive:
        raise DiffScopeError(f"Windows drive paths are not allowed: {raw!r}")

    path = Path(raw)
    if path.is_absolute():
        resolved = path.resolve(strict=False)
        for root in (after_root, before_root):
            try:
                relative = resolved.relative_to(root)
            except ValueError:
                continue
            return _normalise_relative_path(relative.as_posix(), allow_root=True)
        raise DiffScopeError(f"editable path is outside the compared workspace roots: {raw!r}")

    return _normalise_relative_path(raw, allow_root=True)


def _normalise_relative_path(raw: str, *, allow_root: bool) -> str:
    posix = PurePosixPath(raw)
    if posix.is_absolute():
        raise DiffScopeError(f"absolute workspace paths are not allowed: {raw!r}")

    parts = posix.parts
    if not parts or parts == (".",):
        if allow_root:
            return "."
        raise DiffScopeError("workspace path must identify a file")
    if any(part in ("", ".", "..") for part in parts):
        raise DiffScopeError(f"path traversal is not allowed: {raw!r}")
    return "/".join(parts)


def _collect_changes(before_root: Path, after_root: Path, scopes: Iterable[_EditableScope]) -> list[FileChange]:
    before = _snapshot_tree(before_root)
    after = _snapshot_tree(after_root)
    editable_scopes = tuple(scopes)

    changes: list[FileChange] = []
    for path in sorted(set(before) | set(after)):
        before_fp = before.get(path)
        after_fp = after.get(path)
        if before_fp == after_fp:
            continue
        if before_fp is None:
            status: ChangeStatus = "added"
        elif after_fp is None:
            status = "deleted"
        else:
            status = "modified"
        change_kind = after_fp.kind if after_fp is not None else before_fp.kind

        changes.append(
            FileChange(
                path=path,
                status=status,
                inside_editable_scope=_inside_any_editable_scope(path, editable_scopes),
                before_sha256=None if before_fp is None else before_fp.sha256,
                after_sha256=None if after_fp is None else after_fp.sha256,
                before_size_bytes=None if before_fp is None else before_fp.size_bytes,
                after_size_bytes=None if after_fp is None else after_fp.size_bytes,
                kind=change_kind,
            )
        )
    return changes


def _snapshot_tree(root: Path) -> dict[str, _Fingerprint]:
    snapshot: dict[str, _Fingerprint] = {}
    for path in sorted(root.rglob("*")):
        path_stat = path.lstat()
        mode = path_stat.st_mode
        if stat.S_ISDIR(mode):
            continue

        relative = _normalise_relative_path(path.relative_to(root).as_posix(), allow_root=False)
        if stat.S_ISLNK(mode):
            target = os.readlink(path)
            data = target.encode("utf-8", errors="surrogateescape")
            snapshot[relative] = _Fingerprint(
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
                kind="symlink",
            )
            continue

        if not stat.S_ISREG(mode):
            data = f"{stat.S_IFMT(mode)}:{path_stat.st_size}".encode("ascii")
            snapshot[relative] = _Fingerprint(
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=path_stat.st_size,
                kind="special",
            )
            continue

        data = path.read_bytes()
        snapshot[relative] = _Fingerprint(
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            kind="file",
        )
    return snapshot


def _inside_any_editable_scope(path: str, scopes: Iterable[_EditableScope]) -> bool:
    return any(_inside_editable_scope(path, scope) for scope in scopes)


def _inside_editable_scope(path: str, scope: _EditableScope) -> bool:
    if scope.path == ".":
        return True
    if path == scope.path:
        return True
    return scope.is_dir and path.startswith(f"{scope.path}/")


def _read_change_bytes(root: Path, relative_path: str) -> bytes:
    path = root.joinpath(*PurePosixPath(relative_path).parts)
    return path.read_bytes()


__all__ = [
    "DiffScopeError",
    "DiffScopeReport",
    "DiffScopeVerdict",
    "FileChange",
    "build_patch_text",
    "diff_workspaces",
    "evaluate_diff_scope",
    "write_diff_scope_artifacts",
]
