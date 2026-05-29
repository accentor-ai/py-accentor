from __future__ import annotations

"""Deterministic prompt construction for decorator-level agent stages."""

import inspect
import math
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from accentor.record.observe import ObservationPolicy, REDACTED_VALUE, json_safe


SUCCESS_CRITERIA_PARAMETER = "success_criteria"
SUCCESS_CRITERIA_PLACEHOLDER = "{success_criteria}"

_SENSITIVE_CONFIG_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)
_IGNORED_CONFIG_NAMES = frozenset(
    {
        "criteria_description",
        "description",
        "expects_parsed",
        "use_parsed_candidate",
        "use_parsed_output",
        "uses_parsed_candidate",
    }
)


def _clean_line(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("prompt metadata must not contain non-finite floats")
        return value
    if isinstance(value, Path):
        return os.fspath(value)
    if isinstance(value, Enum):
        return _json_ready(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=repr)]
    return repr(value)


def _as_mapping_proxy(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class PromptSection:
    """A named prompt fragment with redaction-aware serialization."""

    name: str
    text: str
    sensitive: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("prompt section name is required")
        object.__setattr__(self, "metadata", _as_mapping_proxy(self.metadata))

    def to_dict(
        self,
        *,
        redact: bool = False,
        policy: ObservationPolicy | None = None,
    ) -> dict[str, Any]:
        redaction_policy = policy or ObservationPolicy()
        text = redaction_policy.replacement if redact and self.sensitive else self.text
        data = {
            "name": self.name,
            "text": text,
            "sensitive": self.sensitive,
            "metadata": _json_ready(self.metadata),
        }
        safe = json_safe(data)
        if not isinstance(safe, dict):
            raise TypeError("prompt section serialization must produce a mapping")
        if redact:
            redacted = redaction_policy.redact(safe)
            if not isinstance(redacted, dict):
                raise TypeError("prompt section redaction must produce a mapping")
            return redacted
        return safe


@dataclass(frozen=True, slots=True)
class CompiledPrompt:
    """Prompt text plus the deterministic sections used to construct it."""

    prompt: str
    sections: tuple[PromptSection, ...] = ()
    injected_parameters: Mapping[str, str] = field(default_factory=dict)
    placeholder_replacements: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "prompt", str(self.prompt))
        object.__setattr__(self, "sections", tuple(self.sections))
        object.__setattr__(self, "injected_parameters", _as_mapping_proxy(self.injected_parameters))
        object.__setattr__(self, "placeholder_replacements", tuple(self.placeholder_replacements))

    def to_dict(
        self,
        *,
        redact: bool = False,
        policy: ObservationPolicy | None = None,
    ) -> dict[str, Any]:
        redaction_policy = policy or ObservationPolicy()
        prompt = redaction_policy.replacement if redact else self.prompt
        injected = (
            {key: redaction_policy.replacement for key in self.injected_parameters}
            if redact
            else dict(self.injected_parameters)
        )
        data = {
            "prompt": prompt,
            "sections": [
                section.to_dict(redact=redact, policy=redaction_policy)
                for section in self.sections
            ],
            "injected_parameters": injected,
            "placeholder_replacements": list(self.placeholder_replacements),
        }
        safe = json_safe(data)
        if not isinstance(safe, dict):
            raise TypeError("compiled prompt serialization must produce a mapping")
        if redact:
            redacted = redaction_policy.redact(safe)
            if not isinstance(redacted, dict):
                raise TypeError("compiled prompt redaction must produce a mapping")
            return redacted
        return safe

    def redacted(self, *, policy: ObservationPolicy | None = None) -> dict[str, Any]:
        return self.to_dict(redact=True, policy=policy)


def _sensitive_name(name: str) -> bool:
    normalized = name.lower().replace("-", "_").strip()
    return any(fragment in normalized for fragment in _SENSITIVE_CONFIG_FRAGMENTS)


def _redact_config_value(name: str | None, value: Any) -> Any:
    if name is not None and _sensitive_name(name):
        return REDACTED_VALUE
    if isinstance(value, Mapping):
        return {
            str(key): _redact_config_value(str(key), item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_config_value(None, item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_redact_config_value(None, item) for item in sorted(value, key=repr)]
    return value


def _stable_repr(value: Any) -> str:
    if value == REDACTED_VALUE:
        return repr(REDACTED_VALUE)
    if isinstance(value, re.Pattern):
        return repr(value.pattern)
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, Path):
        return repr(os.fspath(value))
    if isinstance(value, Enum):
        return _stable_repr(value.value)
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


def _validator_name(validator: Any) -> str:
    if validator is None:
        return "validator"
    if isinstance(validator, str):
        return validator
    if isinstance(validator, type):
        return validator.__name__
    name = getattr(validator, "__name__", None)
    if name:
        return str(name)
    return validator.__class__.__name__


def _public_config(validator: Any) -> dict[str, Any]:
    names: set[str] = set()
    if is_dataclass(validator) and not isinstance(validator, type):
        names.update(item.name for item in fields(validator))
    try:
        names.update(vars(validator))
    except TypeError:
        pass

    config: dict[str, Any] = {}
    for name in sorted(names):
        if name.startswith("_") or name in _IGNORED_CONFIG_NAMES:
            continue
        value = getattr(validator, name)
        if callable(value):
            continue
        config[name] = _redact_config_value(name, value)
    return config


def _explicit_criteria_description(validator: Any) -> str | None:
    description = getattr(validator, "description", None)
    if description:
        return _clean_line(description)

    private_description = getattr(validator, "_criteria_description", None)
    if private_description:
        return _clean_line(private_description)

    try:
        static_attr = inspect.getattr_static(validator, "criteria_description")
    except AttributeError:
        static_attr = None

    if isinstance(static_attr, property):
        getter = static_attr.fget
        if (
            getattr(getter, "__module__", None) != "accentor.evaluate.validation.base"
            or getattr(getter, "__qualname__", None) != "Validator.criteria_description"
        ):
            value = getattr(validator, "criteria_description", None)
            if value:
                return _clean_line(value)
    elif static_attr is not None:
        value = getattr(validator, "criteria_description", None)
        if value:
            return _clean_line(value)

    return None


def criteria_text(validator: Any) -> str:
    """Return the safe deterministic criterion text for one validator."""

    explicit = _explicit_criteria_description(validator)
    if explicit:
        return explicit

    name = _validator_name(validator)
    config = _public_config(validator)
    if not config:
        return name
    args = ", ".join(f"{key}={_stable_repr(value)}" for key, value in config.items())
    return f"{name}({args})"


def _bulleted_block(title: str, bullets: Sequence[str]) -> str:
    cleaned = tuple(_clean_line(bullet) for bullet in bullets if _clean_line(bullet))
    if not cleaned:
        return ""
    return "\n".join((title, *(f"- {bullet}" for bullet in cleaned)))


def _as_items(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, Mapping)):
        return (value,)
    if hasattr(value, "messages") or hasattr(value, "diagnostics"):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _messages_from_failure(failure: Any) -> tuple[str, ...]:
    if failure is None:
        return ()
    if isinstance(failure, bytes):
        return (_clean_line(failure.decode("utf-8", errors="replace")),)
    if isinstance(failure, str):
        return (_clean_line(failure),)
    if isinstance(failure, Mapping):
        if "messages" in failure:
            return tuple(_clean_line(message) for message in _as_items(failure["messages"]))
        if "errors" in failure:
            return tuple(_clean_line(message) for message in _as_items(failure["errors"]))
        if "message" in failure:
            return (_clean_line(failure["message"]),)
        return ()

    ok = getattr(failure, "ok", None)
    if ok is True:
        return ()

    messages = getattr(failure, "messages", None)
    if messages:
        return tuple(_clean_line(message) for message in _as_items(messages))
    errors = getattr(failure, "errors", None)
    if errors:
        return tuple(_clean_line(message) for message in _as_items(errors))
    message = getattr(failure, "message", None)
    if message:
        return (_clean_line(message),)
    return ()


def build_prompt_sections(
    *,
    validators: Iterable[Any] = (),
    previous_validation_results: Any = None,
    previous_failures: Any = None,
) -> tuple[PromptSection, ...]:
    """Build the deterministic v1 criteria and retry-feedback sections."""

    criteria = tuple(
        text
        for text in (criteria_text(validator) for validator in validators)
        if text
    )
    failure_messages: list[str] = []
    for failure in (*_as_items(previous_validation_results), *_as_items(previous_failures)):
        failure_messages.extend(message for message in _messages_from_failure(failure) if message)

    sections: list[PromptSection] = []
    criteria_block = _bulleted_block("Success criteria:", criteria)
    if criteria_block:
        sections.append(
            PromptSection(
                name="success_criteria",
                text=criteria_block,
                sensitive=True,
                metadata={"validator_count": len(criteria)},
            )
        )

    failure_block = _bulleted_block("Previous validation failures:", failure_messages)
    if failure_block:
        sections.append(
            PromptSection(
                name="previous_validation_failures",
                text=failure_block,
                sensitive=True,
                metadata={"failure_count": len(failure_messages)},
            )
        )
    return tuple(sections)


def build_success_criteria_text(
    *,
    validators: Iterable[Any] = (),
    previous_validation_results: Any = None,
    previous_failures: Any = None,
) -> str:
    """Return the exact text injected into the v1 ``success_criteria`` slot."""

    sections = build_prompt_sections(
        validators=validators,
        previous_validation_results=previous_validation_results,
        previous_failures=previous_failures,
    )
    return "\n\n".join(section.text for section in sections)


def _accepts_parameter(source: Callable[..., Any], parameter: str) -> bool:
    try:
        signature = inspect.signature(source)
    except (TypeError, ValueError):
        return False
    return any(
        item.name == parameter or item.kind is inspect.Parameter.VAR_KEYWORD
        for item in signature.parameters.values()
    )


class PromptCompiler:
    """Compile prompt source callables or template strings into agent text."""

    def __init__(
        self,
        *,
        validators: Iterable[Any] = (),
        inject_criteria: bool = False,
    ) -> None:
        self.validators = tuple(validators)
        self.inject_criteria = bool(inject_criteria)

    def compile(
        self,
        source: Callable[..., Any] | str | None,
        *,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        validators: Iterable[Any] | None = None,
        inject_criteria: bool | None = None,
        previous_validation_results: Any = None,
        previous_failures: Any = None,
    ) -> CompiledPrompt:
        selected_validators = self.validators if validators is None else tuple(validators)
        should_inject = self.inject_criteria if inject_criteria is None else bool(inject_criteria)

        all_sections = build_prompt_sections(
            validators=selected_validators,
            previous_validation_results=previous_validation_results,
            previous_failures=previous_failures,
        ) if should_inject else ()
        injected_text = "\n\n".join(section.text for section in all_sections)

        call_kwargs = dict(kwargs or {})
        injected_parameters: dict[str, str] = {}
        parameter_requested = callable(source) and _accepts_parameter(source, SUCCESS_CRITERIA_PARAMETER)
        if should_inject and parameter_requested:
            call_kwargs[SUCCESS_CRITERIA_PARAMETER] = injected_text
            injected_parameters[SUCCESS_CRITERIA_PARAMETER] = injected_text

        if callable(source):
            prompt_source = source(*tuple(args), **call_kwargs)
        elif source is None:
            prompt_source = ""
        else:
            prompt_source = source

        prompt = "" if prompt_source is None else str(prompt_source)
        replacements: list[str] = []
        placeholder_requested = should_inject and SUCCESS_CRITERIA_PLACEHOLDER in prompt
        if placeholder_requested:
            prompt = prompt.replace(SUCCESS_CRITERIA_PLACEHOLDER, injected_text)
            replacements.append(SUCCESS_CRITERIA_PARAMETER)

        sections = all_sections if parameter_requested or placeholder_requested else ()
        return CompiledPrompt(
            prompt=prompt,
            sections=sections,
            injected_parameters=injected_parameters if sections else {},
            placeholder_replacements=tuple(replacements),
        )


__all__ = [
    "CompiledPrompt",
    "PromptCompiler",
    "PromptSection",
    "SUCCESS_CRITERIA_PARAMETER",
    "SUCCESS_CRITERIA_PLACEHOLDER",
    "build_prompt_sections",
    "build_success_criteria_text",
    "criteria_text",
]
