"""Filesystem artifact storage for one task or workflow invocation."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, BinaryIO, Iterator, TextIO


class ArtifactPathError(ValueError):
    """Raised when an artifact name would escape the artifact root."""


@dataclass(frozen=True)
class ArtifactRecord:
    """Small JSON-stable record suitable for inclusion in ``TaskResult``."""

    name: str
    path: str
    size_bytes: int
    sha256: str
    content_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.content_type is None:
            data.pop("content_type")
        return data


def _normalise_artifact_name(name: str | Path) -> str:
    raw = str(name)
    if not raw:
        raise ArtifactPathError("artifact name must not be empty")
    if "\x00" in raw:
        raise ArtifactPathError("artifact name must not contain NUL bytes")

    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise ArtifactPathError(f"absolute artifact names are not allowed: {raw!r}")
    if "\\" in raw:
        raise ArtifactPathError(f"backslash path separators are not allowed: {raw!r}")

    parts = posix.parts
    if not parts or parts == (".",):
        raise ArtifactPathError("artifact name must identify a file")
    if any(part in ("", ".", "..") for part in parts):
        raise ArtifactPathError(f"path traversal is not allowed: {raw!r}")

    return "/".join(parts)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ArtifactStore:
    """Path-safe local artifact store rooted at one invocation directory."""

    def __init__(self, artifact_root: str | Path) -> None:
        self.artifact_root = Path(artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self._root = self.artifact_root.resolve(strict=True)
        if not self._root.is_dir():
            raise NotADirectoryError(f"artifact root is not a directory: {self._root}")

    @property
    def root(self) -> Path:
        return self._root

    def _artifact_path(self, name: str | Path, *, create_parent: bool = True) -> tuple[str, Path]:
        normalised = _normalise_artifact_name(name)
        path = self._root.joinpath(*PurePosixPath(normalised).parts)

        parent = path.parent
        if create_parent:
            parent.mkdir(parents=True, exist_ok=True)
        elif not parent.exists():
            raise FileNotFoundError(parent)

        resolved_parent = parent.resolve(strict=True)
        if not _is_relative_to(resolved_parent, self._root):
            raise ArtifactPathError(f"artifact parent escapes artifact root: {normalised!r}")

        if path.exists() or path.is_symlink():
            resolved_path = path.resolve(strict=True)
            if not _is_relative_to(resolved_path, self._root):
                raise ArtifactPathError(f"artifact path escapes artifact root: {normalised!r}")

        return normalised, path

    def path(self, name: str | Path) -> Path:
        """Return the safe absolute filesystem path for an artifact name."""

        _, path = self._artifact_path(name)
        return path

    def open(
        self,
        name: str | Path,
        mode: str = "r",
        *,
        encoding: str = "utf-8",
        newline: str | None = None,
    ) -> TextIO | BinaryIO:
        """Open an artifact after applying root-confined path validation."""

        _, path = self._artifact_path(name, create_parent=any(flag in mode for flag in "wax+"))
        if "b" in mode:
            return path.open(mode)
        return path.open(mode, encoding=encoding, newline=newline)

    def write_text(
        self,
        name: str | Path,
        text: str,
        *,
        encoding: str = "utf-8",
        content_type: str = "text/plain",
    ) -> ArtifactRecord:
        _, path = self._artifact_path(name)
        path.write_text(text, encoding=encoding)
        return self.record(name, content_type=content_type)

    def read_text(self, name: str | Path, *, encoding: str = "utf-8") -> str:
        _, path = self._artifact_path(name, create_parent=False)
        return path.read_text(encoding=encoding)

    def write_bytes(
        self,
        name: str | Path,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> ArtifactRecord:
        _, path = self._artifact_path(name)
        path.write_bytes(data)
        return self.record(name, content_type=content_type)

    def read_bytes(self, name: str | Path) -> bytes:
        _, path = self._artifact_path(name, create_parent=False)
        return path.read_bytes()

    def write_json(
        self,
        name: str | Path,
        data: Any,
        *,
        indent: int = 2,
        sort_keys: bool = True,
    ) -> ArtifactRecord:
        text = json.dumps(data, indent=indent, sort_keys=sort_keys)
        return self.write_text(name, f"{text}\n", content_type="application/json")

    def read_json(self, name: str | Path) -> Any:
        return json.loads(self.read_text(name))

    def copy_file(
        self,
        source: str | Path,
        name: str | Path | None = None,
        *,
        content_type: str | None = None,
    ) -> ArtifactRecord:
        source_path = Path(source)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        artifact_name = name if name is not None else source_path.name
        _, destination = self._artifact_path(artifact_name)
        shutil.copyfile(source_path, destination)
        return self.record(artifact_name, content_type=content_type)

    promote_file = copy_file

    def record(self, name: str | Path, *, content_type: str | None = None) -> ArtifactRecord:
        normalised, path = self._artifact_path(name, create_parent=False)
        if not path.is_file():
            raise FileNotFoundError(path)
        stat = path.stat()
        return ArtifactRecord(
            name=normalised,
            path=str(path),
            size_bytes=stat.st_size,
            sha256=_sha256_file(path),
            content_type=content_type,
        )

    def list_artifacts(self) -> list[ArtifactRecord]:
        records: list[ArtifactRecord] = []
        for path in sorted(self._root.rglob("*")):
            if not path.is_file():
                continue
            resolved = path.resolve(strict=True)
            if not _is_relative_to(resolved, self._root):
                raise ArtifactPathError(f"artifact path escapes artifact root: {path}")
            name = path.relative_to(self._root).as_posix()
            records.append(self.record(name))
        return records

    def iter_artifacts(self) -> Iterator[ArtifactRecord]:
        yield from self.list_artifacts()

    def manifest(self) -> dict[str, Any]:
        artifacts = [record.to_dict() for record in self.list_artifacts()]
        return {
            "artifact_root": str(self._root),
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
        }

    def write_manifest(self, name: str | Path = "artifact_manifest.json") -> ArtifactRecord:
        return self.write_json(name, self.manifest())
