from __future__ import annotations

"""Provider-neutral command permission records."""

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from accentor.core.task.diagnostics import Diagnostic
from accentor.dispatch.agents.base.capabilities import AgentCapabilities


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
class CommandPolicy:
    """Shell/command intent with explicit unsupported-feature diagnostics.

    Accentor v1 does not implement provider-neutral command allowlist or
    denylist enforcement. Those fields are preserved as auditable intent and
    surfaced as diagnostics during policy evaluation.
    """

    enabled: bool
    allowed_commands: tuple[str, ...]
    denied_commands: tuple[str, ...]

    def __init__(
        self,
        enabled: bool | Mapping[str, Any] | None = False,
        *,
        allow_shell: bool | None = None,
        allow: Iterable[object] | object | None = None,
        allowed_commands: Iterable[object] | object | None = None,
        allowlist: Iterable[object] | object | None = None,
        commands: Iterable[object] | object | None = None,
        deny: Iterable[object] | object | None = None,
        denied_commands: Iterable[object] | object | None = None,
        denylist: Iterable[object] | object | None = None,
    ) -> None:
        if isinstance(enabled, Mapping):
            data = enabled
            enabled_value = data.get("enabled", data.get("allow_shell", False))
            allowed_value = data.get(
                "allowed_commands",
                data.get("allow", data.get("allowlist", data.get("commands", allowed_commands))),
            )
            denied_value = data.get("denied_commands", data.get("deny", data.get("denylist", denied_commands)))
        else:
            enabled_value = enabled if allow_shell is None else allow_shell
            allowed_value = allowed_commands if allowed_commands is not None else allow
            if allowed_value is None:
                allowed_value = allowlist
            if allowed_value is None:
                allowed_value = commands
            denied_value = denied_commands if denied_commands is not None else deny
            if denied_value is None:
                denied_value = denylist

        allowed = _string_tuple(allowed_value)
        denied = _string_tuple(denied_value)
        object.__setattr__(self, "enabled", bool(enabled_value) or bool(allowed) or bool(denied))
        object.__setattr__(self, "allowed_commands", allowed)
        object.__setattr__(self, "denied_commands", denied)

    @classmethod
    def disabled(cls) -> "CommandPolicy":
        return cls(False)

    @classmethod
    def from_any(cls, value: "CommandPolicy | Mapping[str, Any] | bool | None") -> "CommandPolicy":
        if isinstance(value, cls):
            return value
        if value is None:
            return cls.disabled()
        if isinstance(value, Mapping):
            return cls(value)
        return cls(bool(value))

    @property
    def allow_shell(self) -> bool:
        return self.enabled

    def provider_flags(self, provider: str | object | None = None) -> dict[str, Any]:
        """Return only provider flags v1 knows how to map.

        Command execution is controlled by provider capability and sandbox
        behavior in v1; there is no provider-neutral allowlist flag to emit.
        """

        return {}

    def to_provider_flags(self, provider: str | object | None = None) -> dict[str, Any]:
        return self.provider_flags(provider)

    def unsupported_diagnostics(
        self,
        provider: str | object | None = None,
        *,
        capabilities: AgentCapabilities | Mapping[str, Any] | object | None = None,
    ) -> tuple[Diagnostic, ...]:
        provider_name = _provider_name(provider)
        diagnostics: list[Diagnostic] = []
        capability_snapshot = AgentCapabilities.from_any(capabilities) if capabilities is not None else None

        if self.enabled and capability_snapshot is not None and not capability_snapshot.supports_shell:
            diagnostics.append(
                Diagnostic.error(
                    code="policy.commands.provider_unsupported",
                    message="The selected provider does not advertise shell command support.",
                    source="dispatch.policy.commands",
                    hint="Choose a provider with shell support or remove command permissions.",
                    details={"provider": provider_name},
                )
            )
        if self.allowed_commands:
            diagnostics.append(
                Diagnostic.error(
                    code="policy.commands.allowlist_unsupported",
                    message="Command allowlists are not enforced by Accentor v1.",
                    source="dispatch.policy.commands",
                    hint="Use provider-side controls or remove command allowlists for v1.",
                    details={"provider": provider_name, "allowed_commands": list(self.allowed_commands)},
                )
            )
        if self.denied_commands:
            diagnostics.append(
                Diagnostic.error(
                    code="policy.commands.denylist_unsupported",
                    message="Command denylists are not enforced by Accentor v1.",
                    source="dispatch.policy.commands",
                    hint="Use provider-side controls or remove command denylists for v1.",
                    details={"provider": provider_name, "denied_commands": list(self.denied_commands)},
                )
            )
        return tuple(diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "allowed_commands": list(self.allowed_commands),
            "denied_commands": list(self.denied_commands),
        }


__all__ = ["CommandPolicy"]
