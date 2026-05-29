"""File-level validators."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from accentor.evaluate.validation.base import (
    ValidationContext,
    ValidationResult,
    Validator,
    ensure_context,
)


_MISSING = object()


@dataclass(frozen=True)
class _LoadedText:
    path: Path
    text: str


@dataclass(frozen=True)
class _LoadedJson:
    path: Path
    data: Any


def _normalise_path_text(path: str | os.PathLike[str]) -> str:
    return os.fspath(path).replace("\\", "/")


def _safe_join(root: Path, relative: Path) -> Path | None:
    root_resolved = root.resolve(strict=False)
    candidate = (root_resolved / relative).resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def _context_roots(context: ValidationContext | None) -> list[Path]:
    if context is None:
        return []

    roots: list[Path] = []
    store = context.artifact_store
    if store is not None:
        for attr in ("root", "artifact_root"):
            value = getattr(store, attr, None)
            if value is not None:
                roots.append(Path(value))
                break
    if context.artifact_root is not None:
        roots.append(context.artifact_root)
    if context.workspace_root is not None:
        roots.append(context.workspace_root)
    if context.cwd is not None:
        roots.append(context.cwd)

    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve(strict=False))
        if key not in seen:
            deduped.append(root)
            seen.add(key)
    return deduped


def _candidate_paths(path: str | os.PathLike[str], context: ValidationContext | None) -> list[Path]:
    raw = Path(path)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw.resolve(strict=False))
    else:
        for root in _context_roots(context):
            joined = _safe_join(root, raw)
            if joined is not None:
                candidates.append(joined)
        candidates.append(raw.resolve(strict=False))

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            deduped.append(candidate)
            seen.add(key)
    return deduped


def _resolve_existing_file(
    path: str | os.PathLike[str],
    context: ValidationContext | None,
) -> tuple[Path | None, list[Path]]:
    candidates = _candidate_paths(path, context)
    for candidate in candidates:
        if candidate.is_file():
            return candidate, candidates
    return None, candidates


def _read_text_file(
    path: str | os.PathLike[str],
    context: ValidationContext | None,
    *,
    validator: Any,
) -> tuple[_LoadedText | None, ValidationResult | None]:
    resolved, candidates = _resolve_existing_file(path, context)
    if resolved is None:
        return None, ValidationResult.failure(
            f"Required file not found: {_normalise_path_text(path)}",
            validator=validator,
            code="validation.file_missing",
            metadata={
                "path": _normalise_path_text(path),
                "checked": [str(candidate) for candidate in candidates],
            },
        )

    try:
        text = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return None, ValidationResult.failure(
            f"File is not valid UTF-8 text: {resolved}",
            validator=validator,
            code="validation.file_read_error",
            metadata={"path": str(resolved), "error": str(exc)},
        )
    except OSError as exc:
        return None, ValidationResult.failure(
            f"Could not read file: {resolved}",
            validator=validator,
            code="validation.file_read_error",
            metadata={"path": str(resolved), "error": str(exc)},
        )
    return _LoadedText(path=resolved, text=text), None


def _load_file_json(
    path: str | os.PathLike[str],
    context: ValidationContext | None = None,
    *,
    validator: Any = "FileRequiredKeys",
) -> tuple[_LoadedJson | None, ValidationResult | None]:
    loaded, failure = _read_text_file(path, context, validator=validator)
    if failure is not None:
        return None, failure
    assert loaded is not None
    try:
        data = json.loads(loaded.text)
    except json.JSONDecodeError as exc:
        return None, ValidationResult.failure(
            f"File is not valid JSON: {loaded.path}: {exc.msg}",
            validator=validator,
            code="validation.file_json_invalid",
            metadata={"path": str(loaded.path), "line": exc.lineno, "column": exc.colno},
        )
    return _LoadedJson(path=loaded.path, data=data), None


def _normalise_text(value: Any) -> str:
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _get_field(data: Any, field: str) -> tuple[bool, Any]:
    current = data
    if isinstance(current, dict) and field in current:
        return True, current[field]

    for part in field.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                return False, None
            if 0 <= index < len(current):
                current = current[index]
                continue
        return False, None
    return True, current


class RequiredFile(Validator):
    """Validate that a file exists."""

    def __init__(self, path: str | os.PathLike[str], description: str | None = None) -> None:
        self.path = path
        self.description = description

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        ctx = ensure_context(candidate, context)
        resolved, candidates = _resolve_existing_file(self.path, ctx)
        if resolved is None:
            return ValidationResult.failure(
                f"Required file not found: {_normalise_path_text(self.path)}",
                validator=self,
                code="validation.file_missing",
                metadata={
                    "path": _normalise_path_text(self.path),
                    "checked": [str(candidate_path) for candidate_path in candidates],
                },
            )
        return ValidationResult.success(
            validator=self.__class__.__name__,
            criteria=self.criteria,
            metadata={"path": str(resolved)},
        )


class FileRequiredKeys(Validator):
    """Validate that a JSON file contains all required top-level keys."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        keys: list[str] | tuple[str, ...] | None = None,
        *,
        description: str | None = None,
    ) -> None:
        self.path = path
        self.keys = tuple(str(key) for key in keys or ())
        self.description = description

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        ctx = ensure_context(candidate, context)
        loaded, failure = _load_file_json(self.path, ctx, validator=self)
        if failure is not None:
            return failure
        assert loaded is not None

        if not isinstance(loaded.data, dict):
            return ValidationResult.failure(
                f"JSON file must contain an object: {loaded.path}",
                validator=self,
                code="validation.file_json_not_object",
                metadata={"path": str(loaded.path), "keys": self.keys},
            )

        missing = tuple(key for key in self.keys if key not in loaded.data)
        if missing:
            return ValidationResult.failure(
                f"JSON file is missing required keys: {', '.join(missing)}",
                validator=self,
                code="validation.required_keys_missing",
                metadata={"path": str(loaded.path), "missing_keys": list(missing), "keys": self.keys},
            )

        return ValidationResult.success(
            validator=self.__class__.__name__,
            criteria=self.criteria,
            metadata={"path": str(loaded.path), "keys": self.keys},
        )


class ExactMatch(Validator):
    """Validate exact file content, parsing JSON when expected is a dict/list."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        expected: Any = _MISSING,
        *,
        field: str | None = None,
        value: Any = _MISSING,
        description: str | None = None,
    ) -> None:
        self.path = path
        self.field = field
        self.expected = value if expected is _MISSING and value is not _MISSING else expected
        self.description = description

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        ctx = ensure_context(candidate, context)

        if self.field is not None:
            loaded_json, failure = _load_file_json(self.path, ctx, validator=self)
            if failure is not None:
                return failure
            assert loaded_json is not None
            found, actual = _get_field(loaded_json.data, self.field)
            if not found:
                return ValidationResult.failure(
                    f"JSON file is missing field: {self.field}",
                    validator=self,
                    code="validation.exact_match_missing_field",
                    metadata={"path": str(loaded_json.path), "field": self.field},
                )
            return self._compare(actual, loaded_json.path, mode="json_field")

        if isinstance(self.expected, (dict, list)):
            loaded_json, failure = _load_file_json(self.path, ctx, validator=self)
            if failure is not None:
                return failure
            assert loaded_json is not None
            return self._compare(loaded_json.data, loaded_json.path, mode="json")

        loaded_text, failure = _read_text_file(self.path, ctx, validator=self)
        if failure is not None:
            return failure
        assert loaded_text is not None
        return self._compare(
            _normalise_text(loaded_text.text),
            loaded_text.path,
            expected=_normalise_text(self.expected),
            mode="text",
        )

    def _compare(
        self,
        actual: Any,
        path: Path,
        *,
        expected: Any = _MISSING,
        mode: str,
    ) -> ValidationResult:
        expected_value = self.expected if expected is _MISSING else expected
        if actual != expected_value:
            return ValidationResult.failure(
                f"File content did not match expected value: {path}",
                validator=self,
                code="validation.exact_match_failed",
                metadata={
                    "path": str(path),
                    "mode": mode,
                    "expected": expected_value,
                    "actual": actual,
                },
            )
        return ValidationResult.success(
            validator=self.__class__.__name__,
            criteria=self.criteria,
            metadata={"path": str(path), "mode": mode},
        )


__all__ = ["ExactMatch", "FileRequiredKeys", "RequiredFile", "_load_file_json"]
