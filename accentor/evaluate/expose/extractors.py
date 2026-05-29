from __future__ import annotations

"""Provider-neutral extraction helpers for validation candidates."""

import inspect
import json
import math
import os
import re
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Callable, Mapping

from accentor.core.task.diagnostics import Diagnostic
from accentor.record.artifacts.store import ArtifactRecord

from .records import ExtractionContext, ExtractionResult, JsonParseFailure


_FENCE_RE = re.compile(r"```(?P<info>[^\r\n`]*)\r?\n(?P<body>.*?)\r?\n?```", re.DOTALL)
_JSON_OPENERS = frozenset(("{", "["))


class Extractor:
    """Base protocol-like class for concrete extractors."""

    def extract(self, candidate: Any = None, context: ExtractionContext | None = None) -> ExtractionResult:
        raise NotImplementedError


def _coerce_context(context: ExtractionContext | Mapping[str, Any] | None) -> ExtractionContext:
    if context is None:
        return ExtractionContext()
    if isinstance(context, ExtractionContext):
        return context
    if isinstance(context, Mapping):
        return ExtractionContext(metadata=context)
    raise TypeError("context must be an ExtractionContext, mapping, or None")


def _coerce_text(candidate: Any, *, encoding: str = "utf-8", errors: str = "replace") -> str:
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, bytes):
        return candidate.decode(encoding, errors=errors)
    if candidate is None:
        return ""
    return str(candidate)


def _is_json_compatible_value(value: Any, *, top_level: bool = True) -> bool:
    if value is None or isinstance(value, (bool, int)):
        return True
    if isinstance(value, str):
        return not top_level
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_compatible_value(item, top_level=False) for item in value)
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str) and _is_json_compatible_value(item, top_level=False)
            for key, item in value.items()
        )
    return False


def _snippet(text: str, position: int | None, *, radius: int = 80) -> str | None:
    if not text:
        return None
    if position is None:
        return text[: radius * 2]
    start = max(0, position - radius)
    end = min(len(text), position + radius)
    return text[start:end]


def _failure_from_error(error: JSONDecodeError, *, source: str, text: str) -> JsonParseFailure:
    return JsonParseFailure(
        message=error.msg,
        position=error.pos,
        line=error.lineno,
        column=error.colno,
        source=source,
        snippet=_snippet(text, error.pos),
    )


def _no_json_failure(*, source: str, text: str) -> JsonParseFailure:
    return JsonParseFailure(
        message="No JSON object, array, or complete JSON value was found in candidate text.",
        source=source,
        snippet=_snippet(text, 0),
    )


def _stripped_with_span(text: str) -> tuple[str, int, int]:
    start = len(text) - len(text.lstrip())
    stripped = text.strip()
    end = start + len(stripped)
    return stripped, start, end


def _parse_full_json(text: str, *, source: str) -> tuple[bool, Any, dict[str, Any], JsonParseFailure | None]:
    stripped, start, end = _stripped_with_span(text)
    if not stripped:
        return False, None, {}, _no_json_failure(source=source, text=text)
    try:
        parsed = json.loads(stripped)
    except JSONDecodeError as error:
        return False, None, {}, _failure_from_error(error, source=source, text=stripped)
    return True, parsed, {"json_source": "full_text", "json_span": [start, end]}, None


def _parse_json_fences(text: str, *, source: str) -> tuple[bool, Any, dict[str, Any], JsonParseFailure | None]:
    first_failure: JsonParseFailure | None = None
    for match in _FENCE_RE.finditer(text):
        info = match.group("info").strip()
        language = info.split()[0].lower() if info else ""
        if language not in {"", "json"}:
            continue
        body = match.group("body")
        body_text, body_start, body_end = _stripped_with_span(body)
        try:
            parsed = json.loads(body_text)
        except JSONDecodeError as error:
            if first_failure is None:
                first_failure = _failure_from_error(error, source=source, text=body_text)
            continue
        absolute_start = match.start("body") + body_start
        absolute_end = match.start("body") + body_end
        return (
            True,
            parsed,
            {
                "json_source": "markdown_fence",
                "json_span": [absolute_start, absolute_end],
                "fence_language": language or None,
            },
            None,
        )
    return False, None, {}, first_failure


def _parse_raw_decode_at_start(
    stripped: str,
    *,
    start_offset: int,
    source: str,
) -> tuple[bool, Any, dict[str, Any], JsonParseFailure | None]:
    decoder = json.JSONDecoder()
    try:
        parsed, end = decoder.raw_decode(stripped, 0)
    except JSONDecodeError as error:
        return False, None, {}, _failure_from_error(error, source=source, text=stripped)
    return (
        True,
        parsed,
        {
            "json_source": "leading_json",
            "json_span": [start_offset, start_offset + end],
        },
        None,
    )


def _parse_embedded_json(text: str, *, source: str) -> tuple[bool, Any, dict[str, Any], JsonParseFailure | None]:
    decoder = json.JSONDecoder()
    first_failure: JsonParseFailure | None = None
    for index, character in enumerate(text):
        if character not in _JSON_OPENERS:
            continue
        try:
            parsed, end = decoder.raw_decode(text, index)
        except JSONDecodeError as error:
            if first_failure is None:
                first_failure = _failure_from_error(error, source=source, text=text)
            continue
        return True, parsed, {"json_source": "embedded_text", "json_span": [index, end]}, None
    return False, None, {}, first_failure or _no_json_failure(source=source, text=text)


def _json_result_from_text(
    text: str,
    *,
    source: str,
    metadata: Mapping[str, Any] | None = None,
) -> ExtractionResult:
    base_metadata = dict(metadata or {})
    ok, parsed, parse_metadata, failure = _parse_full_json(text, source=source)
    if ok:
        return ExtractionResult(
            raw=text,
            parsed=parsed,
            has_parsed=True,
            source=source,
            metadata={**base_metadata, **parse_metadata},
        )

    fence_ok, fenced, fence_metadata, fence_failure = _parse_json_fences(text, source=source)
    if fence_ok:
        return ExtractionResult(
            raw=text,
            parsed=fenced,
            has_parsed=True,
            source=source,
            metadata={**base_metadata, **fence_metadata},
        )

    stripped, start, _ = _stripped_with_span(text)
    if stripped and stripped[0] in _JSON_OPENERS:
        leading_ok, leading, leading_metadata, leading_failure = _parse_raw_decode_at_start(
            stripped,
            start_offset=start,
            source=source,
        )
        if leading_ok:
            return ExtractionResult(
                raw=text,
                parsed=leading,
                has_parsed=True,
                source=source,
                metadata={**base_metadata, **leading_metadata},
            )
        failure = leading_failure or failure
    else:
        embedded_ok, embedded, embedded_metadata, embedded_failure = _parse_embedded_json(text, source=source)
        if embedded_ok:
            return ExtractionResult(
                raw=text,
                parsed=embedded,
                has_parsed=True,
                source=source,
                metadata={**base_metadata, **embedded_metadata},
            )
        failure = fence_failure or embedded_failure or failure

    assert failure is not None
    return ExtractionResult(
        raw=text,
        source=source,
        diagnostics=(failure.to_diagnostic(),),
        parse_failures=(failure,),
        metadata=base_metadata,
    )


def _missing_candidate_result(*, source: str, message: str, code: str, metadata: Mapping[str, Any]) -> ExtractionResult:
    return ExtractionResult(
        raw=None,
        source=source,
        diagnostics=(Diagnostic.error(code, message, source=source, details=metadata),),
        metadata=metadata,
    )


@dataclass(frozen=True, slots=True)
class TextExtractor(Extractor):
    """Expose a candidate as raw text without attempting structured parsing."""

    encoding: str = "utf-8"
    errors: str = "replace"
    source: str = "text"

    def extract(self, candidate: Any = None, context: ExtractionContext | Mapping[str, Any] | None = None) -> ExtractionResult:
        _coerce_context(context)
        text = _coerce_text(candidate, encoding=self.encoding, errors=self.errors)
        return ExtractionResult(
            raw=text,
            source=self.source,
            metadata={"input_type": type(candidate).__name__, "extractor": type(self).__name__},
        )


@dataclass(frozen=True, slots=True)
class JsonExtractor(Extractor):
    """Expose raw text and the first parsed JSON candidate when available."""

    encoding: str = "utf-8"
    errors: str = "replace"
    source: str = "json"

    def extract(self, candidate: Any = None, context: ExtractionContext | Mapping[str, Any] | None = None) -> ExtractionResult:
        _coerce_context(context)
        if _is_json_compatible_value(candidate):
            return ExtractionResult(
                raw=candidate,
                parsed=candidate,
                has_parsed=True,
                source=self.source,
                metadata={"json_source": "python_value", "extractor": type(self).__name__},
            )
        if not isinstance(candidate, (str, bytes)):
            diagnostic = Diagnostic.warning(
                "extraction.unsupported_json_candidate",
                "JSON extraction expects text, bytes, or JSON-compatible Python values.",
                source=self.source,
                details={"candidate_type": type(candidate).__name__},
            )
            return ExtractionResult(
                raw=candidate,
                source=self.source,
                diagnostics=(diagnostic,),
                metadata={"extractor": type(self).__name__, "candidate_type": type(candidate).__name__},
            )
        text = _coerce_text(candidate, encoding=self.encoding, errors=self.errors)
        return _json_result_from_text(
            text,
            source=self.source,
            metadata={"input_type": type(candidate).__name__, "extractor": type(self).__name__},
        )


@dataclass(frozen=True, slots=True)
class FileExtractor(Extractor):
    """Read a text file and optionally expose parsed JSON from its contents."""

    path: str | os.PathLike[str] | None = None
    root: str | os.PathLike[str] | None = None
    encoding: str = "utf-8"
    parse_json: bool = True
    source: str = "file"

    def extract(self, candidate: Any = None, context: ExtractionContext | Mapping[str, Any] | None = None) -> ExtractionResult:
        extraction_context = _coerce_context(context)
        path = self._resolve_path(candidate, extraction_context)
        if path is None:
            return _missing_candidate_result(
                source=self.source,
                code="extraction.file_missing_path",
                message="File extraction requires a file path.",
                metadata={"extractor": type(self).__name__},
            )

        metadata = {"extractor": type(self).__name__, "path": str(path)}
        try:
            text = path.read_text(encoding=self.encoding)
        except FileNotFoundError:
            return _missing_candidate_result(
                source=self.source,
                code="extraction.file_not_found",
                message=f"File was not found: {path}",
                metadata=metadata,
            )
        except OSError as error:
            return ExtractionResult(
                raw=None,
                source=self.source,
                diagnostics=(
                    Diagnostic.error(
                        "extraction.file_read_failed",
                        f"File could not be read: {path}",
                        source=self.source,
                        details={**metadata, "error": str(error)},
                    ),
                ),
                metadata=metadata,
            )

        if not self.parse_json:
            return ExtractionResult(raw=text, source=self.source, metadata=metadata)

        result = _json_result_from_text(text, source=self.source, metadata=metadata)
        return result

    def _resolve_path(self, candidate: Any, context: ExtractionContext) -> Path | None:
        raw_path = self.path if self.path is not None else candidate
        if raw_path is None:
            raw_path = context.path
        if raw_path is None:
            return None
        if not isinstance(raw_path, (str, os.PathLike)):
            return None
        path = Path(raw_path)
        if path.is_absolute():
            return path
        root = Path(self.root) if self.root is not None else context.artifact_root
        return Path(root, path) if root is not None else path


@dataclass(frozen=True, slots=True)
class ArtifactExtractor(Extractor):
    """Read a named artifact from an ArtifactStore, artifact root, or record."""

    artifact_name: str | os.PathLike[str] | None = None
    artifact_store: Any = None
    artifact_root: str | os.PathLike[str] | None = None
    encoding: str = "utf-8"
    parse_json: bool = True
    source: str = "artifact"

    def extract(self, candidate: Any = None, context: ExtractionContext | Mapping[str, Any] | None = None) -> ExtractionResult:
        extraction_context = _coerce_context(context)
        name, path, metadata = self._resolve_artifact(candidate, extraction_context)
        store = self.artifact_store if self.artifact_store is not None else extraction_context.artifact_store

        if store is not None and name is not None:
            try:
                text = store.read_text(name, encoding=self.encoding)
            except FileNotFoundError:
                return _missing_candidate_result(
                    source=self.source,
                    code="extraction.artifact_not_found",
                    message=f"Artifact was not found: {name}",
                    metadata=metadata,
                )
            except OSError as error:
                return ExtractionResult(
                    raw=None,
                    source=self.source,
                    diagnostics=(
                        Diagnostic.error(
                            "extraction.artifact_read_failed",
                            f"Artifact could not be read: {name}",
                            source=self.source,
                            details={**metadata, "error": str(error)},
                        ),
                    ),
                    metadata=metadata,
                )
            return self._result_from_artifact_text(text, metadata)

        if path is None and name is not None:
            root = self.artifact_root if self.artifact_root is not None else extraction_context.artifact_root
            if root is not None:
                path = Path(root, name)

        if path is None:
            return _missing_candidate_result(
                source=self.source,
                code="extraction.artifact_missing_reference",
                message="Artifact extraction requires an artifact name, path, or record.",
                metadata=metadata or {"extractor": type(self).__name__},
            )

        file_result = FileExtractor(
            path=path,
            encoding=self.encoding,
            parse_json=self.parse_json,
            source=self.source,
        ).extract(context=extraction_context)
        return ExtractionResult(
            raw=file_result.raw,
            parsed=file_result.parsed,
            has_parsed=file_result.has_parsed,
            source=self.source,
            diagnostics=file_result.diagnostics,
            parse_failures=file_result.parse_failures,
            metadata={**dict(file_result.metadata), **metadata},
        )

    def _result_from_artifact_text(self, text: str, metadata: Mapping[str, Any]) -> ExtractionResult:
        if not self.parse_json:
            return ExtractionResult(raw=text, source=self.source, metadata=metadata)
        return _json_result_from_text(text, source=self.source, metadata=metadata)

    def _resolve_artifact(
        self,
        candidate: Any,
        context: ExtractionContext,
    ) -> tuple[str | None, Path | None, dict[str, Any]]:
        name: str | None = os.fspath(self.artifact_name) if self.artifact_name is not None else None
        path: Path | None = None
        metadata: dict[str, Any] = {"extractor": type(self).__name__}

        reference = candidate
        if reference is None and context.artifact_name is not None:
            reference = context.artifact_name

        if isinstance(reference, ArtifactRecord):
            name = name or reference.name
            path = Path(reference.path)
            metadata["artifact"] = reference.to_dict()
        elif isinstance(reference, Mapping):
            raw_name = reference.get("name", reference.get("artifact_name"))
            raw_path = reference.get("path")
            if name is None and isinstance(raw_name, (str, os.PathLike)):
                name = os.fspath(raw_name)
            if isinstance(raw_path, (str, os.PathLike)):
                path = Path(raw_path)
            metadata["artifact"] = dict(reference)
        elif isinstance(reference, (str, os.PathLike)):
            name = name or os.fspath(reference)

        if name is not None:
            metadata["artifact_name"] = name
        if path is not None and not path.is_absolute():
            root = self.artifact_root if self.artifact_root is not None else context.artifact_root
            if root is not None:
                path = Path(root, path)
        if path is not None:
            metadata["path"] = str(path)
        return name, path, metadata


@dataclass(frozen=True, slots=True)
class CustomExtractor(Extractor):
    """Adapter for user-provided extraction functions."""

    function: Callable[..., ExtractionResult | Any]
    source: str = "custom"

    def extract(self, candidate: Any = None, context: ExtractionContext | Mapping[str, Any] | None = None) -> ExtractionResult:
        extraction_context = _coerce_context(context)
        try:
            signature = inspect.signature(self.function)
        except (TypeError, ValueError):
            value = self.function(candidate, extraction_context)
        else:
            positional = [
                parameter
                for parameter in signature.parameters.values()
                if parameter.kind
                in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                }
            ]
            accepts_varargs = any(
                parameter.kind is inspect.Parameter.VAR_POSITIONAL
                for parameter in signature.parameters.values()
            )
            accepts_keyword_context = any(
                parameter.name == "context"
                and parameter.kind
                in {
                    inspect.Parameter.KEYWORD_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                }
                for parameter in signature.parameters.values()
            )
            if accepts_varargs or len(positional) >= 2:
                value = self.function(candidate, extraction_context)
            elif accepts_keyword_context:
                value = self.function(candidate, context=extraction_context)
            else:
                value = self.function(candidate)

        if isinstance(value, ExtractionResult):
            return value
        return ExtractionResult(raw=value, source=self.source, metadata={"extractor": type(self).__name__})


def extract_text(candidate: Any = None, context: ExtractionContext | Mapping[str, Any] | None = None) -> ExtractionResult:
    return TextExtractor().extract(candidate, context)


def extract_json(candidate: Any = None, context: ExtractionContext | Mapping[str, Any] | None = None) -> ExtractionResult:
    return JsonExtractor().extract(candidate, context)


def extract_file(
    candidate: Any = None,
    context: ExtractionContext | Mapping[str, Any] | None = None,
    *,
    path: str | os.PathLike[str] | None = None,
    parse_json: bool = True,
) -> ExtractionResult:
    return FileExtractor(path=path, parse_json=parse_json).extract(candidate, context)


def extract_artifact(
    candidate: Any = None,
    context: ExtractionContext | Mapping[str, Any] | None = None,
    *,
    artifact_name: str | os.PathLike[str] | None = None,
    parse_json: bool = True,
) -> ExtractionResult:
    return ArtifactExtractor(artifact_name=artifact_name, parse_json=parse_json).extract(candidate, context)


__all__ = [
    "ArtifactExtractor",
    "CustomExtractor",
    "Extractor",
    "FileExtractor",
    "JsonExtractor",
    "TextExtractor",
    "extract_artifact",
    "extract_file",
    "extract_json",
    "extract_text",
]
