from __future__ import annotations

"""Validation records and composition helpers."""

import json
import math
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, fields, is_dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from accentor.core.task.diagnostics import Diagnostic


_MISSING = object()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("validation report values must not contain non-finite floats")
        return value
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, Enum):
        return _json_ready(value.value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=repr)]
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return repr(value)


def _message_tuple(messages: str | Sequence[str] | None) -> tuple[str, ...]:
    if messages is None:
        return ()
    if isinstance(messages, str):
        return (messages,) if messages else ()
    return tuple(str(message) for message in messages if str(message))


def _diagnostic_tuple(
    diagnostics: Sequence[Diagnostic | Mapping[str, Any]] | None,
) -> tuple[Diagnostic, ...]:
    if diagnostics is None:
        return ()
    normalised: list[Diagnostic] = []
    for diagnostic in diagnostics:
        if isinstance(diagnostic, Diagnostic):
            normalised.append(diagnostic)
        elif isinstance(diagnostic, Mapping):
            normalised.append(Diagnostic(**diagnostic))
        else:
            raise TypeError("diagnostics must contain Diagnostic objects or mappings")
    return tuple(normalised)


def _validator_name(validator: Any) -> str:
    if validator is None:
        return "validator"
    if isinstance(validator, str):
        return validator
    if isinstance(validator, type):
        return validator.__name__
    return validator.__class__.__name__


def validator_slug(validator: "Validator | type[Validator] | str") -> str:
    """Return a stable snake-case identifier for reports and diagnostics."""

    name = _validator_name(validator)
    slug = re.sub(r"(?<!^)(?=[A-Z])", "_", name).replace("-", "_").lower()
    return re.sub(r"[^a-z0-9_]+", "_", slug).strip("_") or "validator"


class ValidationContext:
    """Context supplied to validators for one candidate."""

    def __init__(
        self,
        *,
        candidate: Any = _MISSING,
        raw_candidate: Any = _MISSING,
        raw_output: Any = _MISSING,
        raw_text: str | None = None,
        parsed_candidate: Any = _MISSING,
        parsed_output: Any = _MISSING,
        parsed_json: Any = _MISSING,
        parsed_available: bool | None = None,
        has_parsed_output: bool | None = None,
        has_parsed_json: bool | None = None,
        json_error: str | None = None,
        artifact_root: str | os.PathLike[str] | None = None,
        workspace_root: str | os.PathLike[str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
        artifact_store: Any = None,
        metadata: Mapping[str, Any] | None = None,
        diagnostics: Sequence[Diagnostic | Mapping[str, Any]] | None = None,
        **extra: Any,
    ) -> None:
        raw = raw_candidate
        if raw is _MISSING:
            raw = candidate
        if raw is _MISSING:
            raw = raw_output
        if raw is _MISSING and raw_text is not None:
            raw = raw_text
        if raw is _MISSING:
            raw = None

        parsed = parsed_candidate
        if parsed is _MISSING:
            parsed = parsed_output
        if parsed is _MISSING:
            parsed = parsed_json

        parsed_flag = parsed is not _MISSING
        for flag in (parsed_available, has_parsed_output, has_parsed_json):
            if flag is not None:
                parsed_flag = bool(flag)

        parsed_value = None if parsed is _MISSING else parsed
        if raw_text is None and isinstance(raw, str):
            raw_text = raw

        details = dict(metadata or {})
        details.update(extra)

        self.raw_candidate = raw
        self.candidate = raw
        self.raw_output = raw
        self.raw_text = raw_text
        self.parsed_candidate = parsed_value
        self.parsed_output = parsed_value
        self.parsed_json = parsed_value
        self.parsed_available = parsed_flag
        self.has_parsed_output = parsed_flag
        self.has_parsed_json = parsed_flag
        self.json_error = json_error
        self.artifact_root = Path(artifact_root) if artifact_root is not None else None
        self.workspace_root = Path(workspace_root) if workspace_root is not None else None
        self.cwd = Path(cwd) if cwd is not None else None
        self.artifact_store = artifact_store
        self.metadata = MappingProxyType(details)
        self.diagnostics = _diagnostic_tuple(diagnostics)

    @classmethod
    def from_candidate(
        cls,
        candidate: Any,
        *,
        parsed_candidate: Any = _MISSING,
        parsed_json: Any = _MISSING,
        artifact_root: str | os.PathLike[str] | None = None,
        workspace_root: str | os.PathLike[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
        diagnostics: Sequence[Diagnostic | Mapping[str, Any]] | None = None,
        parse_json: bool = True,
    ) -> "ValidationContext":
        parsed = parsed_candidate if parsed_candidate is not _MISSING else parsed_json
        parsed_available = parsed is not _MISSING
        json_error = None
        if not parsed_available and isinstance(candidate, str) and parse_json:
            try:
                parsed = json.loads(candidate)
                parsed_available = True
            except json.JSONDecodeError as exc:
                json_error = str(exc)
        elif not parsed_available and isinstance(candidate, (Mapping, list, tuple)):
            parsed = list(candidate) if isinstance(candidate, tuple) else candidate
            parsed_available = True

        return cls(
            raw_candidate=candidate,
            raw_text=candidate if isinstance(candidate, str) else None,
            parsed_candidate=None if parsed is _MISSING else parsed,
            parsed_available=parsed_available,
            json_error=json_error,
            artifact_root=artifact_root,
            workspace_root=workspace_root,
            metadata=metadata,
            diagnostics=diagnostics,
        )

    @property
    def raw(self) -> Any:
        return self.raw_candidate

    @property
    def parsed(self) -> Any:
        return self.parsed_candidate

    def with_candidate(self, candidate: Any) -> "ValidationContext":
        return ValidationContext(
            raw_candidate=candidate,
            raw_text=candidate if isinstance(candidate, str) else self.raw_text,
            parsed_candidate=self.parsed_candidate,
            parsed_available=self.parsed_available,
            json_error=self.json_error,
            artifact_root=self.artifact_root,
            workspace_root=self.workspace_root,
            cwd=self.cwd,
            artifact_store=self.artifact_store,
            metadata=self.metadata,
            diagnostics=self.diagnostics,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_candidate": _json_ready(self.raw_candidate),
            "raw_text": self.raw_text,
            "parsed_candidate": _json_ready(self.parsed_candidate) if self.parsed_available else None,
            "parsed_available": self.parsed_available,
            "json_error": self.json_error,
            "artifact_root": os.fspath(self.artifact_root) if self.artifact_root is not None else None,
            "workspace_root": os.fspath(self.workspace_root) if self.workspace_root is not None else None,
            "cwd": os.fspath(self.cwd) if self.cwd is not None else None,
            "metadata": _json_ready(self.metadata),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


class ValidationResult:
    """Result returned by every validator."""

    def __init__(
        self,
        ok: bool,
        messages: str | Sequence[str] | None = None,
        *,
        errors: str | Sequence[str] | None = None,
        diagnostics: Sequence[Diagnostic | Mapping[str, Any]] | None = None,
        validator: str | None = None,
        criteria: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        details: Mapping[str, Any] | None = None,
        children: Sequence["ValidationResult"] | None = None,
        parsed_json_required: bool = False,
    ) -> None:
        if not isinstance(ok, bool):
            raise TypeError("ok must be a bool")
        message_tuple = _message_tuple(messages)
        error_tuple = _message_tuple(errors)
        if message_tuple and not error_tuple:
            error_tuple = message_tuple
        if error_tuple and not message_tuple:
            message_tuple = error_tuple

        self.ok = ok
        self.messages = message_tuple
        self.errors = error_tuple
        diagnostic_tuple = _diagnostic_tuple(diagnostics)
        if not ok and error_tuple and not diagnostic_tuple:
            diagnostic_tuple = tuple(
                Diagnostic.error(
                    "validation.failed",
                    message,
                    source=validator,
                    details=_json_ready({"validator": validator} if validator else {}),
                )
                for message in error_tuple
            )
        self.diagnostics = diagnostic_tuple
        self.validator = validator
        self.criteria = criteria
        self.metadata = MappingProxyType(dict(metadata if metadata is not None else details or {}))
        self.details = self.metadata
        self.children = tuple(children or ())
        self.parsed_json_required = parsed_json_required

    @classmethod
    def success(
        cls,
        *,
        validator: str | None = None,
        criteria: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        details: Mapping[str, Any] | None = None,
        children: Sequence["ValidationResult"] | None = None,
        parsed_json_required: bool = False,
    ) -> "ValidationResult":
        return cls(
            True,
            validator=validator,
            criteria=criteria,
            metadata=metadata,
            details=details,
            children=children,
            parsed_json_required=parsed_json_required,
        )

    pass_ = success

    @classmethod
    def failure(
        cls,
        messages: str | Sequence[str],
        *,
        validator: Any = None,
        code: str = "validation.failed",
        criteria: str | None = None,
        diagnostics: Sequence[Diagnostic | Mapping[str, Any]] | None = None,
        metadata: Mapping[str, Any] | None = None,
        details: Mapping[str, Any] | None = None,
        children: Sequence["ValidationResult"] | None = None,
        parsed_json_required: bool = False,
    ) -> "ValidationResult":
        name = _validator_name(validator) if validator is not None else None
        normalised = _message_tuple(messages)
        payload = dict(metadata if metadata is not None else details or {})
        if name is not None:
            payload.setdefault("validator", name)
        generated = tuple(
            Diagnostic.error(code, message, source=name, details=_json_ready(payload))
            for message in normalised
        )
        return cls(
            False,
            messages=normalised,
            errors=normalised,
            diagnostics=tuple(diagnostics or ()) or generated,
            validator=name,
            criteria=criteria,
            metadata=metadata,
            details=details,
            children=children,
            parsed_json_required=parsed_json_required,
        )

    fail = failure

    @property
    def message(self) -> str | None:
        return self.messages[0] if self.messages else None

    def __bool__(self) -> bool:
        return self.ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "messages": list(self.messages),
            "errors": list(self.errors),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "validator": self.validator,
            "criteria": self.criteria,
            "metadata": _json_ready(self.metadata),
            "children": [child.to_dict() for child in self.children],
        }


def ensure_context(
    value: Any = None,
    context: ValidationContext | None = None,
    *,
    candidate: Any = _MISSING,
) -> ValidationContext:
    """Normalise both ``ensure_context(candidate, context)`` and keyword styles."""

    if isinstance(value, ValidationContext) and context is None:
        ctx = value
        selected = None if candidate is _MISSING else candidate
    else:
        ctx = context
        selected = value if candidate is _MISSING else candidate

    if ctx is None:
        return ValidationContext.from_candidate(selected)
    if selected is not None and selected is not _MISSING and ctx.raw_candidate is None:
        return ctx.with_candidate(selected)
    return ctx


def _public_config(validator: Any) -> dict[str, Any]:
    names: set[str] = set()
    if is_dataclass(validator) and not isinstance(validator, type):
        names.update(item.name for item in fields(validator))
    try:
        names.update(vars(validator))
    except TypeError:
        pass
    ignored = {
        "description",
        "criteria_description",
        "use_parsed_output",
        "use_parsed_candidate",
        "uses_parsed_candidate",
        "expects_parsed",
    }
    config: dict[str, Any] = {}
    for name in sorted(names):
        if name.startswith("_") or name in ignored:
            continue
        value = getattr(validator, name)
        if callable(value):
            continue
        config[name] = value
    return config


def _stable_repr(value: Any) -> str:
    if isinstance(value, re.Pattern):
        return repr(value.pattern)
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, Mapping):
        return "{" + ", ".join(
            f"{key!r}: {_stable_repr(item)}"
            for key, item in sorted(value.items(), key=lambda entry: repr(entry[0]))
        ) + "}"
    if isinstance(value, (set, frozenset)):
        return "[" + ", ".join(_stable_repr(item) for item in sorted(value, key=repr)) + "]"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_stable_repr(item) for item in value) + "]"
    return repr(value)


def criteria_description(validator: Any) -> str:
    explicit = getattr(validator, "description", None) or getattr(validator, "_criteria_description", None)
    if explicit:
        return str(explicit)

    name = _validator_name(validator)
    config = _public_config(validator)
    if not config:
        return name
    args = ", ".join(f"{key}={_stable_repr(value)}" for key, value in config.items())
    return f"{name}({args})"


class Validator:
    """Base validator with ``check(output) -> list[str]`` compatibility."""

    description: str | None = None
    use_parsed_output = False

    @property
    def criteria(self) -> str:
        return criteria_description(self)

    @property
    def criteria_description(self) -> str:
        return criteria_description(self)

    @criteria_description.setter
    def criteria_description(self, value: str | None) -> None:
        self._criteria_description = value

    def check(self, output: Any) -> Sequence[str]:
        return ()

    def validate(
        self,
        candidate: Any = None,
        context: ValidationContext | None = None,
    ) -> ValidationResult:
        ctx = ensure_context(candidate, context)
        if (
            self.use_parsed_output
            or bool(getattr(self, "use_parsed_candidate", False))
        ) and ctx.parsed_available:
            output = ctx.parsed_candidate
        elif ctx.raw_text is not None:
            output = ctx.raw_text
        else:
            output = candidate
        try:
            messages = self.check(output)
        except Exception as exc:  # pragma: no cover - defensive adapter boundary
            return ValidationResult.failure(
                f"{_validator_name(self)} raised {exc.__class__.__name__}: {exc}",
                validator=self,
                code="validation.validator_error",
            )
        if messages:
            return ValidationResult.failure(messages, validator=self, criteria=self.criteria)
        return ValidationResult.success(validator=_validator_name(self), criteria=self.criteria)


class UnsupportedValidator(Validator):
    """Base for modules intentionally not implemented in v1."""

    feature = "validator"

    def __init__(self, *args: Any, feature: str | None = None, **kwargs: Any) -> None:
        self.feature = feature or self.feature
        self.args = args
        self.kwargs = kwargs
        self._criteria_description = f"[N] {self.feature}"

    def validate(
        self,
        candidate: Any = None,
        context: ValidationContext | None = None,
    ) -> ValidationResult:
        return ValidationResult.failure(
            f"[N] {self.feature} is not implemented in Accentor v1.",
            validator=self,
            code="validation.unsupported",
            metadata={"status": "[N]", "feature": self.feature},
        )

    def check(self, output: Any) -> Sequence[str]:
        return [f"[N] {self.feature} is not implemented in Accentor v1."]


ValidatorLike = Validator | Callable[[Any], bool | Sequence[str] | ValidationResult]


def _run_validator(
    validator: ValidatorLike,
    candidate: Any,
    context: ValidationContext | None,
) -> ValidationResult:
    validate = getattr(validator, "validate", None)
    if callable(validate):
        return validate(candidate, context)

    outcome = validator(candidate)  # type: ignore[misc]
    name = _validator_name(validator)
    if isinstance(outcome, ValidationResult):
        return outcome
    if isinstance(outcome, bool):
        if outcome:
            return ValidationResult.success(validator=name)
        return ValidationResult.failure("Validator returned False.", validator=name)
    messages = _message_tuple(outcome)
    if messages:
        return ValidationResult.failure(messages, validator=name)
    return ValidationResult.success(validator=name)


class _CompositeValidator(Validator):
    def __init__(self, validators: Sequence[ValidatorLike], *, mode: str, description: str | None = None) -> None:
        if len(validators) == 1 and isinstance(validators[0], Iterable) and not isinstance(
            validators[0],
            (str, bytes),
        ):
            validators = tuple(validators[0])  # type: ignore[assignment]
        if not validators:
            raise ValueError(f"{mode} requires at least one validator")
        self.validators = tuple(validators)
        self.mode = mode
        self.description = description

    @property
    def criteria_description(self) -> str:
        joiner = " and " if self.mode == "all_of" else " or "
        return joiner.join(criteria_description(validator) for validator in self.validators)


class _AllOf(_CompositeValidator):
    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        results = [_run_validator(validator, candidate, context) for validator in self.validators]
        failures = [result for result in results if not result.ok]
        if not failures:
            return ValidationResult.success(validator="all_of", children=results)
        return ValidationResult.failure(
            [message for result in failures for message in result.messages],
            validator="all_of",
            metadata={"failed": len(failures), "total": len(results)},
            children=results,
        )


class _AnyOf(_CompositeValidator):
    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        results = [_run_validator(validator, candidate, context) for validator in self.validators]
        if any(result.ok for result in results):
            return ValidationResult.success(validator="any_of", children=results)
        messages = [message for result in results for message in result.messages]
        return ValidationResult.failure(
            messages or "No validators passed.",
            validator="any_of",
            metadata={"failed": len(results), "total": len(results)},
            children=results,
        )


class _Not(Validator):
    def __init__(self, validator: ValidatorLike, description: str | None = None) -> None:
        self.validator = validator
        self.description = description

    @property
    def criteria_description(self) -> str:
        return f"not {criteria_description(self.validator)}"

    def validate(self, candidate: Any = None, context: ValidationContext | None = None) -> ValidationResult:
        result = _run_validator(self.validator, candidate, context)
        if not result.ok:
            return ValidationResult.success(validator="not_", children=[result])
        return ValidationResult.failure(
            f"Negated validator passed: {criteria_description(self.validator)}",
            validator="not_",
            children=[result],
        )


def all_of(*validators: ValidatorLike, description: str | None = None) -> Validator:
    return _AllOf(validators, mode="all_of", description=description)


def any_of(*validators: ValidatorLike, description: str | None = None) -> Validator:
    return _AnyOf(validators, mode="any_of", description=description)


def not_(validator: ValidatorLike, description: str | None = None) -> Validator:
    return _Not(validator, description=description)


def _path_tokens(path: str) -> tuple[str | int, ...]:
    tokens: list[str | int] = []
    for part in str(path).split("."):
        if not part:
            continue
        index = 0
        matched = False
        for match in re.finditer(r"([^\[\]]+)|\[(\d+)\]", part):
            matched = True
            if match.start() != index:
                raise ValueError(f"invalid field path: {path}")
            if match.group(1) is not None:
                tokens.append(match.group(1))
            else:
                tokens.append(int(match.group(2)))
            index = match.end()
        if not matched or index != len(part):
            raise ValueError(f"invalid field path: {path}")
    return tuple(tokens)


def get_path(value: Any, path: str | None) -> Any:
    if path is None or path == "":
        return value
    current = value
    for token in _path_tokens(path):
        if isinstance(token, int):
            if not isinstance(current, Sequence) or isinstance(current, (str, bytes)):
                return _MISSING
            if token < 0 or token >= len(current):
                return _MISSING
            current = current[token]
            continue
        if not isinstance(current, Mapping) or token not in current:
            return _MISSING
        current = current[token]
    return current


def stringify_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(value, sort_keys=True)
    return str(value)


__all__ = [
    "_MISSING",
    "UnsupportedValidator",
    "ValidationContext",
    "ValidationResult",
    "Validator",
    "all_of",
    "any_of",
    "criteria_description",
    "ensure_context",
    "get_path",
    "not_",
    "stringify_text",
    "validator_slug",
]
