"""Strict root-confined path policy helpers.

The v1 path policy is intentionally small: normalize paths under an explicit
root, reject ambiguous or escaping input, and evaluate allow/deny declarations
with deny patterns taking precedence.
"""

from __future__ import annotations

import fnmatch
import os
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable


MAX_PATH_SEGMENT_LENGTH = 255
MAX_PATH_TEXT_LENGTH = 4096

PathLike = str | os.PathLike[str]
PatternSource = PathLike | Iterable[PathLike]


class PathPolicyError(ValueError):
    """Raised when a path or policy pattern is unsafe or invalid."""


@dataclass(frozen=True, slots=True)
class NormalizedPath:
    """A path normalized and proven to resolve inside a policy root."""

    root: Path
    path: Path
    relative_path: str
    requested_path: str
    requested_relative_path: str
    existed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "path": str(self.path),
            "relative_path": self.relative_path,
            "requested_path": self.requested_path,
            "requested_relative_path": self.requested_relative_path,
            "existed": self.existed,
        }


@dataclass(frozen=True, slots=True)
class PathPolicyDecision:
    """Provider-neutral verdict for one path policy check."""

    allowed: bool
    path: str
    relative_path: str | None = None
    requested_relative_path: str | None = None
    absolute_path: str | None = None
    reason: str | None = None
    matched_allow: str | None = None
    matched_deny: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.allowed

    @property
    def violating_path(self) -> str:
        return self.relative_path or self.requested_relative_path or self.path

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "path": self.path,
            "relative_path": self.relative_path,
            "requested_relative_path": self.requested_relative_path,
            "absolute_path": self.absolute_path,
            "reason": self.reason,
            "matched_allow": self.matched_allow,
            "matched_deny": self.matched_deny,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class PathPolicyBatchDecision:
    """Aggregate verdict for a collection of path checks."""

    allowed: bool
    decisions: tuple[PathPolicyDecision, ...]
    violating_paths: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "violating_paths": list(self.violating_paths),
            "decisions": [decision.to_dict() for decision in self.decisions],
        }


def _coerce_path(value: PathLike, *, label: str) -> str:
    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise PathPolicyError(f"{label} must be a string or path-like value") from exc
    if isinstance(raw, bytes):
        raise PathPolicyError(f"{label} must be text, not bytes")
    if not isinstance(raw, str):
        raise PathPolicyError(f"{label} must be text")
    if raw == "":
        raise PathPolicyError(f"{label} must not be empty")
    return raw


def _reject_unsafe_text(raw: str, *, label: str) -> None:
    if len(raw) > MAX_PATH_TEXT_LENGTH:
        raise PathPolicyError(f"{label} is too long")
    if "\x00" in raw:
        raise PathPolicyError(f"{label} must not contain NUL bytes")
    if "\n" in raw or "\r" in raw:
        raise PathPolicyError(f"{label} must not contain newlines")
    if raw != unicodedata.normalize("NFC", raw):
        raise PathPolicyError(f"{label} must use canonical NFC unicode normalization")


def _validated_posix_segments(
    raw: str,
    *,
    label: str,
    allow_absolute: bool,
    allow_root: bool = True,
) -> tuple[str, ...]:
    _reject_unsafe_text(raw, label=label)

    if "\\" in raw:
        raise PathPolicyError(f"{label} must use POSIX '/' separators")
    if raw.startswith("//"):
        raise PathPolicyError(f"{label} must not use network-style absolute paths")

    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if windows.drive or windows.is_absolute():
        raise PathPolicyError(f"Windows-style absolute {label}s are not allowed: {raw!r}")
    if posix.is_absolute() and not allow_absolute:
        raise PathPolicyError(f"absolute {label}s are not allowed: {raw!r}")

    text = raw.lstrip("/") if posix.is_absolute() else raw
    if text in ("", "."):
        if allow_root:
            return ()
        raise PathPolicyError(f"{label} must identify a path below the root")

    segments = tuple(text.split("/"))
    for segment in segments:
        if segment == "":
            raise PathPolicyError(f"{label} must not contain empty path segments: {raw!r}")
        if segment == ".":
            raise PathPolicyError(f"{label} must not contain '.' path segments: {raw!r}")
        if segment == "..":
            raise PathPolicyError(f"{label} must not contain '..' traversal: {raw!r}")
        if len(segment) > MAX_PATH_SEGMENT_LENGTH:
            raise PathPolicyError(f"{label} segment is too long: {segment[:32]!r}")
    return segments


def _normalize_root(root: PathLike) -> Path:
    raw = _coerce_path(root, label="root")
    _reject_unsafe_text(raw, label="root")
    try:
        resolved = Path(raw).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise PathPolicyError(f"root does not exist: {raw!r}") from exc
    except OSError as exc:
        raise PathPolicyError(f"root could not be resolved: {raw!r}") from exc
    if not resolved.is_dir():
        raise PathPolicyError(f"root must be a directory: {resolved}")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _relative_posix(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    relative_text = relative.as_posix()
    return relative_text if relative_text else "."


def _relative_from_segments(segments: tuple[str, ...]) -> str:
    return "/".join(segments) if segments else "."


def normalize_under_root(
    root: PathLike,
    path: PathLike,
    *,
    allow_absolute: bool = False,
    must_exist: bool = False,
) -> NormalizedPath:
    """Normalize ``path`` and prove its resolved target stays under ``root``.

    Relative inputs are interpreted below ``root``. Absolute inputs are rejected
    by default and, when explicitly allowed, must still resolve below ``root``.
    Existing symlinks are followed during resolution so symlink escapes are
    rejected before a caller reads or writes the resulting path.
    """

    root_path = _normalize_root(root)
    raw = _coerce_path(path, label="path")
    segments = _validated_posix_segments(
        raw,
        label="path",
        allow_absolute=allow_absolute,
        allow_root=False,
    )

    if PurePosixPath(raw).is_absolute():
        candidate = Path(raw)
        requested_relative_path: str | None = None
    else:
        candidate = root_path.joinpath(*segments) if segments else root_path
        requested_relative_path = _relative_from_segments(segments)

    try:
        resolved = candidate.resolve(strict=must_exist)
    except FileNotFoundError as exc:
        raise PathPolicyError(f"path does not exist: {raw!r}") from exc
    except (OSError, RuntimeError) as exc:
        raise PathPolicyError(f"path could not be resolved safely: {raw!r}") from exc

    if not _is_relative_to(resolved, root_path):
        raise PathPolicyError(f"path escapes root: {raw!r}")

    relative_path = _relative_posix(resolved, root_path)
    if requested_relative_path is None:
        requested_relative_path = relative_path

    return NormalizedPath(
        root=root_path,
        path=resolved,
        relative_path=relative_path,
        requested_path=raw,
        requested_relative_path=requested_relative_path,
        existed=candidate.exists() or candidate.is_symlink(),
    )


def normalize_path(
    root: PathLike,
    path: PathLike,
    *,
    allow_absolute: bool = False,
    must_exist: bool = False,
) -> NormalizedPath:
    """Alias for :func:`normalize_under_root`."""

    return normalize_under_root(root, path, allow_absolute=allow_absolute, must_exist=must_exist)


def normalize_policy_pattern(pattern: PathLike) -> str:
    """Validate and normalize a relative allow/deny pattern."""

    raw = _coerce_path(pattern, label="pattern")
    segments = _validated_posix_segments(raw, label="pattern", allow_absolute=False)
    return _relative_from_segments(segments)


def _has_glob(pattern: str) -> bool:
    return any(char in pattern for char in "*?[")


@lru_cache(maxsize=4096)
def _match_segments(path_parts: tuple[str, ...], pattern_parts: tuple[str, ...]) -> bool:
    if not pattern_parts:
        return not path_parts

    head, *tail_list = pattern_parts
    tail = tuple(tail_list)
    if head == "**":
        if not tail:
            return True
        return any(_match_segments(path_parts[index:], tail) for index in range(len(path_parts) + 1))

    if not path_parts:
        return False
    return fnmatch.fnmatchcase(path_parts[0], head) and _match_segments(path_parts[1:], tail)


def _parts_for_match(relative_path: str) -> tuple[str, ...]:
    return () if relative_path == "." else tuple(relative_path.split("/"))


def _pattern_matches_relative(pattern: str, relative_path: str) -> bool:
    if not _has_glob(pattern):
        if pattern == ".":
            return relative_path == "."
        return relative_path == pattern or relative_path.startswith(f"{pattern}/")

    return _match_segments(_parts_for_match(relative_path), _parts_for_match(pattern))


def path_matches_pattern(relative_path: PathLike, pattern: PathLike) -> bool:
    """Return whether a normalized relative path matches a policy pattern."""

    path_text = normalize_policy_pattern(relative_path)
    pattern_text = normalize_policy_pattern(pattern)
    return _pattern_matches_relative(pattern_text, path_text)


def _matches_normalized_path(pattern: str, normalized: NormalizedPath) -> bool:
    if _pattern_matches_relative(pattern, normalized.relative_path):
        return True
    if normalized.requested_relative_path != normalized.relative_path:
        return _pattern_matches_relative(pattern, normalized.requested_relative_path)
    return False


def _iter_patterns(source: PatternSource) -> Iterable[PathLike]:
    if isinstance(source, (str, os.PathLike)):
        yield source
        return
    yield from source


def _collect_patterns(*sources: PatternSource | None) -> tuple[bool, tuple[str, ...]]:
    saw_source = False
    patterns: list[str] = []
    for source in sources:
        if source is None:
            continue
        saw_source = True
        patterns.extend(normalize_policy_pattern(pattern) for pattern in _iter_patterns(source))
    return saw_source, tuple(patterns)


class PathPolicy:
    """Root-scoped allow/deny path policy.

    ``allowed`` defaults to ``("**",)`` when no allow/read/edit declarations are
    supplied. Passing an explicit empty allow collection denies every path that
    is not already rejected by normalization or a deny pattern.
    """

    __slots__ = ("allow_absolute", "allowed", "denied", "must_exist", "root")

    def __init__(
        self,
        root: PathLike,
        allowed: PatternSource | None = None,
        denied: PatternSource | None = None,
        *,
        allow: PatternSource | None = None,
        deny: PatternSource | None = None,
        allowed_paths: PatternSource | None = None,
        denied_paths: PatternSource | None = None,
        allow_paths: PatternSource | None = None,
        deny_paths: PatternSource | None = None,
        allowed_patterns: PatternSource | None = None,
        denied_patterns: PatternSource | None = None,
        readable: PatternSource | None = None,
        readable_paths: PatternSource | None = None,
        editable: PatternSource | None = None,
        editable_paths: PatternSource | None = None,
        allow_absolute: bool = False,
        must_exist: bool = False,
    ) -> None:
        saw_allowed, allowed_patterns = _collect_patterns(
            allowed,
            allow,
            allowed_paths,
            allow_paths,
            allowed_patterns,
            readable,
            readable_paths,
            editable,
            editable_paths,
        )
        _, denied_patterns = _collect_patterns(
            denied,
            deny,
            denied_paths,
            deny_paths,
            denied_patterns,
        )

        self.root = _normalize_root(root)
        self.allowed = allowed_patterns if saw_allowed else ("**",)
        self.denied = denied_patterns
        self.allow_absolute = allow_absolute
        self.must_exist = must_exist

    @property
    def allowed_paths(self) -> tuple[str, ...]:
        return self.allowed

    @property
    def denied_paths(self) -> tuple[str, ...]:
        return self.denied

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "allowed": list(self.allowed),
            "denied": list(self.denied),
            "allow_absolute": self.allow_absolute,
            "must_exist": self.must_exist,
        }

    def normalize(self, path: PathLike, *, must_exist: bool | None = None) -> NormalizedPath:
        return normalize_under_root(
            self.root,
            path,
            allow_absolute=self.allow_absolute,
            must_exist=self.must_exist if must_exist is None else must_exist,
        )

    def check(self, path: PathLike, *, must_exist: bool | None = None) -> PathPolicyDecision:
        try:
            requested_path = _coerce_path(path, label="path")
            normalized = self.normalize(path, must_exist=must_exist)
        except PathPolicyError as exc:
            if isinstance(path, (str, os.PathLike)):
                requested_raw = os.fspath(path)
                requested_path = requested_raw if isinstance(requested_raw, str) else repr(requested_raw)
            else:
                requested_path = repr(path)
            return PathPolicyDecision(
                allowed=False,
                path=requested_path,
                reason="invalid_path",
                error=str(exc),
            )

        for pattern in self.denied:
            if _matches_normalized_path(pattern, normalized):
                return PathPolicyDecision(
                    allowed=False,
                    path=normalized.requested_path,
                    relative_path=normalized.relative_path,
                    requested_relative_path=normalized.requested_relative_path,
                    absolute_path=str(normalized.path),
                    reason="denied",
                    matched_deny=pattern,
                )

        for pattern in self.allowed:
            if _matches_normalized_path(pattern, normalized):
                return PathPolicyDecision(
                    allowed=True,
                    path=normalized.requested_path,
                    relative_path=normalized.relative_path,
                    requested_relative_path=normalized.requested_relative_path,
                    absolute_path=str(normalized.path),
                    reason="allowed",
                    matched_allow=pattern,
                )

        return PathPolicyDecision(
            allowed=False,
            path=normalized.requested_path,
            relative_path=normalized.relative_path,
            requested_relative_path=normalized.requested_relative_path,
            absolute_path=str(normalized.path),
            reason="not_allowed",
        )

    def allows(self, path: PathLike, *, must_exist: bool | None = None) -> bool:
        return self.check(path, must_exist=must_exist).allowed

    def evaluate(self, path: PathLike, *, must_exist: bool | None = None) -> PathPolicyDecision:
        return self.check(path, must_exist=must_exist)

    is_allowed = allows

    def require_allowed(self, path: PathLike, *, must_exist: bool | None = None) -> NormalizedPath:
        decision = self.check(path, must_exist=must_exist)
        if not decision.allowed:
            detail = decision.error or decision.reason or "path is not allowed"
            raise PathPolicyError(f"{detail}: {decision.path!r}")
        return self.normalize(path, must_exist=must_exist)

    def check_paths(
        self,
        paths: Iterable[PathLike],
        *,
        must_exist: bool | None = None,
    ) -> PathPolicyBatchDecision:
        decisions = tuple(self.check(path, must_exist=must_exist) for path in paths)
        violations = tuple(decision.violating_path for decision in decisions if not decision.allowed)
        return PathPolicyBatchDecision(
            allowed=not violations,
            decisions=decisions,
            violating_paths=violations,
        )

    def evaluate_paths(
        self,
        paths: Iterable[PathLike],
        *,
        must_exist: bool | None = None,
    ) -> PathPolicyBatchDecision:
        return self.check_paths(paths, must_exist=must_exist)


def check_path(
    root: PathLike,
    path: PathLike,
    allowed: PatternSource | None = None,
    denied: PatternSource | None = None,
    *,
    allow_absolute: bool = False,
    must_exist: bool = False,
) -> PathPolicyDecision:
    """Evaluate one path against a temporary :class:`PathPolicy`."""

    return PathPolicy(
        root,
        allowed=allowed,
        denied=denied,
        allow_absolute=allow_absolute,
        must_exist=must_exist,
    ).check(path)


def check_paths(
    root: PathLike,
    paths: Iterable[PathLike],
    allowed: PatternSource | None = None,
    denied: PatternSource | None = None,
    *,
    allow_absolute: bool = False,
    must_exist: bool = False,
) -> PathPolicyBatchDecision:
    """Evaluate several paths against a temporary :class:`PathPolicy`."""

    return PathPolicy(
        root,
        allowed=allowed,
        denied=denied,
        allow_absolute=allow_absolute,
        must_exist=must_exist,
    ).check_paths(paths)


def is_path_allowed(
    root: PathLike,
    path: PathLike,
    allowed: PatternSource | None = None,
    denied: PatternSource | None = None,
    *,
    allow_absolute: bool = False,
    must_exist: bool = False,
) -> bool:
    """Return only the boolean verdict for one path check."""

    return check_path(
        root,
        path,
        allowed=allowed,
        denied=denied,
        allow_absolute=allow_absolute,
        must_exist=must_exist,
    ).allowed


__all__ = [
    "MAX_PATH_SEGMENT_LENGTH",
    "MAX_PATH_TEXT_LENGTH",
    "NormalizedPath",
    "PathPolicy",
    "PathPolicyBatchDecision",
    "PathPolicyDecision",
    "PathPolicyError",
    "check_path",
    "check_paths",
    "is_path_allowed",
    "normalize_path",
    "normalize_policy_pattern",
    "normalize_under_root",
    "path_matches_pattern",
]
