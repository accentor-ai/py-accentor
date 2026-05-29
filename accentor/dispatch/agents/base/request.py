from __future__ import annotations

"""Provider-neutral request records for agent adapters."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


REDACTED_VALUE = "[REDACTED]"
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "content",
        "customer_note",
        "input",
        "message",
        "password",
        "prompt",
        "request",
        "secret",
        "secret_ref",
        "text",
        "token",
    }
)


def _plain_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _plain_value(to_dict())
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    return value


def _copied_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return {str(key): _plain_value(item) for key, item in (value or {}).items()}


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if text_key.lower() in _SENSITIVE_KEYS:
                redacted[text_key] = REDACTED_VALUE
            else:
                redacted[text_key] = _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True, init=False)
class AgentRequest:
    """Input envelope shared by all agent adapter implementations."""

    prompt: str | None
    messages: tuple[Mapping[str, Any], ...]
    workspace: Any | None
    permissions: Mapping[str, Any]
    timeout_seconds: float | None
    provider_options: Mapping[str, Any]
    metadata: Mapping[str, Any]

    def __init__(
        self,
        prompt: str | None = None,
        *,
        messages: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
        workspace: Any | None = None,
        permissions: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
        timeout: float | None = None,
        provider_options: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if timeout_seconds is not None and timeout is not None and timeout_seconds != timeout:
            raise ValueError("timeout_seconds and timeout aliases must match when both are provided")

        if provider_options is not None and options is not None and provider_options != options:
            raise ValueError("provider_options and options aliases must match when both are provided")

        copied_messages = tuple(_copied_mapping(message) for message in (messages or ()))
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "messages", copied_messages)
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "permissions", _copied_mapping(permissions))
        object.__setattr__(
            self,
            "timeout_seconds",
            float(timeout_seconds if timeout_seconds is not None else timeout)
            if timeout_seconds is not None or timeout is not None
            else None,
        )
        object.__setattr__(self, "provider_options", _copied_mapping(provider_options or options))
        object.__setattr__(self, "metadata", _copied_mapping(metadata))

    @property
    def timeout(self) -> float | None:
        return self.timeout_seconds

    @property
    def options(self) -> Mapping[str, Any]:
        return self.provider_options

    def to_dict(self, *, redact: bool = False) -> dict[str, Any]:
        prompt = REDACTED_VALUE if redact and self.prompt is not None else self.prompt
        messages = [_plain_value(message) for message in self.messages]
        data = {
            "prompt": prompt,
            "messages": messages,
            "workspace": _plain_value(self.workspace),
            "permissions": _plain_value(self.permissions),
            "timeout_seconds": self.timeout_seconds,
            "provider_options": _plain_value(self.provider_options),
            "metadata": _plain_value(self.metadata),
        }
        return _redact_value(data) if redact else data

    def redacted(self) -> dict[str, Any]:
        """Return a safe serialized request without mutating this request."""

        return self.to_dict(redact=True)


__all__ = ["AgentRequest", "REDACTED_VALUE"]
