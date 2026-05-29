from __future__ import annotations

"""Environment permission and redaction records."""

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from accentor.core.task.diagnostics import Diagnostic


REDACTED_ENV_VALUE = "[REDACTED]"
PRESENT_ENV_VALUE = "[PRESENT]"


def _string_tuple(values: Iterable[object] | object | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        return (str(values),)
    try:
        return tuple(str(value) for value in values)  # type: ignore[arg-type]
    except TypeError:
        return (str(values),)


def _provider_name(provider: str | object | None) -> str:
    if provider is None:
        return "generic"
    if isinstance(provider, str):
        return provider.lower()
    name = getattr(provider, "name", None)
    return str(name if name is not None else type(provider).__name__).lower()


@dataclass(frozen=True, slots=True, init=False)
class EnvironmentPolicy:
    """Environment inheritance, allow/deny intent, and safe redaction records."""

    inherit: bool
    allowed_variables: tuple[str, ...]
    denied_variables: tuple[str, ...]
    redacted_variables: tuple[str, ...]

    def __init__(
        self,
        inherit: bool | Mapping[str, Any] = True,
        *,
        allow: Iterable[object] | object | None = None,
        allowed_variables: Iterable[object] | object | None = None,
        deny: Iterable[object] | object | None = None,
        denied_variables: Iterable[object] | object | None = None,
        redact: Iterable[object] | object | None = None,
        redacted: Iterable[object] | object | None = None,
        redacted_variables: Iterable[object] | object | None = None,
    ) -> None:
        if isinstance(inherit, Mapping):
            data = inherit
            inherit_value = data.get("inherit", True)
            allowed_value = data.get("allowed_variables", data.get("allow", allow))
            denied_value = data.get("denied_variables", data.get("deny", deny))
            redacted_value = data.get(
                "redacted_variables",
                data.get("redact", data.get("redacted", redact)),
            )
        else:
            inherit_value = inherit
            allowed_value = allowed_variables if allowed_variables is not None else allow
            denied_value = denied_variables if denied_variables is not None else deny
            redacted_value = redacted_variables if redacted_variables is not None else redact
            if redacted_value is None:
                redacted_value = redacted

        object.__setattr__(self, "inherit", bool(inherit_value))
        object.__setattr__(self, "allowed_variables", _string_tuple(allowed_value))
        object.__setattr__(self, "denied_variables", _string_tuple(denied_value))
        object.__setattr__(self, "redacted_variables", _string_tuple(redacted_value))

    @classmethod
    def default(cls) -> "EnvironmentPolicy":
        return cls()

    @classmethod
    def from_any(cls, value: "EnvironmentPolicy | Mapping[str, Any] | None") -> "EnvironmentPolicy":
        if isinstance(value, cls):
            return value
        if value is None:
            return cls.default()
        if isinstance(value, Mapping):
            return cls(value)
        raise TypeError("environment policy must be an EnvironmentPolicy, mapping, or None")

    @property
    def allow(self) -> tuple[str, ...]:
        return self.allowed_variables

    @property
    def deny(self) -> tuple[str, ...]:
        return self.denied_variables

    @property
    def redact(self) -> tuple[str, ...]:
        return self.redacted_variables

    def provider_flags(self, provider: str | object | None = None) -> dict[str, Any]:
        """Return only provider flags v1 knows how to map."""

        return {}

    def to_provider_flags(self, provider: str | object | None = None) -> dict[str, Any]:
        return self.provider_flags(provider)

    def unsupported_diagnostics(self, provider: str | object | None = None) -> tuple[Diagnostic, ...]:
        provider_name = _provider_name(provider)
        diagnostics: list[Diagnostic] = []
        if self.allowed_variables or self.denied_variables:
            diagnostics.append(
                Diagnostic.error(
                    code="policy.environment.enforcement_unsupported",
                    message="Environment allow/deny enforcement is not supported by Accentor v1.",
                    source="dispatch.policy.environment",
                    hint="Prepare the provider process environment outside Accentor or remove allow/deny rules.",
                    details={
                        "provider": provider_name,
                        "allowed_variables": list(self.allowed_variables),
                        "denied_variables": list(self.denied_variables),
                    },
                )
            )
        return tuple(diagnostics)

    def selected_keys(self, environment: Mapping[str, object] | None = None) -> tuple[str, ...]:
        if environment is None:
            keys = set(self.allowed_variables) | set(self.redacted_variables) | set(self.denied_variables)
        elif self.inherit and not self.allowed_variables:
            keys = {str(key) for key in environment}
        else:
            keys = {str(key) for key in self.allowed_variables if str(key) in environment}
            keys.update(str(key) for key in self.redacted_variables if str(key) in environment)
            keys.update(str(key) for key in self.denied_variables if str(key) in environment)
        return tuple(sorted(keys))

    def redaction_record(self, environment: Mapping[str, object] | None = None) -> dict[str, Any]:
        """Return a redaction-safe environment observation record.

        The record intentionally stores presence/redaction metadata rather than
        raw environment values.
        """

        denied = set(self.denied_variables)
        redacted = set(self.redacted_variables)
        variables: dict[str, str] = {}
        for key in self.selected_keys(environment):
            if key in denied:
                continue
            variables[key] = REDACTED_ENV_VALUE if key in redacted else PRESENT_ENV_VALUE
        return {
            "inherit": self.inherit,
            "allowed_variables": list(self.allowed_variables),
            "denied_variables": list(self.denied_variables),
            "redacted_variables": list(self.redacted_variables),
            "variables": variables,
            "redacted": sorted(key for key in variables if variables[key] == REDACTED_ENV_VALUE),
        }

    def apply(self, environment: Mapping[str, object]) -> dict[str, str]:
        """Return a redacted, best-effort view of the environment.

        This helper is for deterministic tests and records. It should not be
        treated as provider-side process environment enforcement.
        """

        denied = set(self.denied_variables)
        redacted = set(self.redacted_variables)
        if self.inherit and not self.allowed_variables:
            keys = [str(key) for key in environment]
        else:
            keys = [key for key in self.allowed_variables if key in environment]
            keys.extend(key for key in self.redacted_variables if key in environment and key not in keys)

        result: dict[str, str] = {}
        for key in keys:
            if key in denied:
                continue
            result[key] = REDACTED_ENV_VALUE if key in redacted else str(environment[key])
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "inherit": self.inherit,
            "allowed_variables": list(self.allowed_variables),
            "denied_variables": list(self.denied_variables),
            "redacted_variables": list(self.redacted_variables),
        }


__all__ = ["EnvironmentPolicy", "PRESENT_ENV_VALUE", "REDACTED_ENV_VALUE"]
