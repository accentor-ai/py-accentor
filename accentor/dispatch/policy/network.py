from __future__ import annotations

"""Provider-neutral network permission records."""

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from accentor.core.task.diagnostics import Diagnostic


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
class NetworkPolicy:
    """Network intent plus the narrow provider flags Accentor v1 can express.

    V1 supports a general network intent record and Codex's search flag. Host
    allowlists/denylists are intentionally recorded as unsupported diagnostics
    rather than pretending a provider-neutral runtime firewall exists.
    """

    enabled: bool
    search: bool
    allowed_hosts: tuple[str, ...]
    denied_hosts: tuple[str, ...]

    def __init__(
        self,
        enabled: bool | Mapping[str, Any] | None = False,
        *,
        search: bool = False,
        allowed_hosts: Iterable[object] | object | None = None,
        allow_hosts: Iterable[object] | object | None = None,
        allowlist: Iterable[object] | object | None = None,
        host_allowlist: Iterable[object] | object | None = None,
        denied_hosts: Iterable[object] | object | None = None,
        deny_hosts: Iterable[object] | object | None = None,
        denylist: Iterable[object] | object | None = None,
        host_denylist: Iterable[object] | object | None = None,
    ) -> None:
        if isinstance(enabled, Mapping):
            data = enabled
            enabled_value = data.get("enabled", data.get("network", data.get("allow_network", False)))
            search_value = data.get("search", data.get("allow_search", search))
            allowed_value = data.get(
                "allowed_hosts",
                data.get("allow_hosts", data.get("allowlist", data.get("host_allowlist", allowed_hosts))),
            )
            denied_value = data.get(
                "denied_hosts",
                data.get("deny_hosts", data.get("denylist", data.get("host_denylist", denied_hosts))),
            )
        else:
            enabled_value = enabled
            search_value = search
            allowed_value = allowed_hosts if allowed_hosts is not None else allow_hosts
            if allowed_value is None:
                allowed_value = allowlist
            if allowed_value is None:
                allowed_value = host_allowlist
            denied_value = denied_hosts if denied_hosts is not None else deny_hosts
            if denied_value is None:
                denied_value = denylist
            if denied_value is None:
                denied_value = host_denylist

        allowed = _string_tuple(allowed_value)
        denied = _string_tuple(denied_value)
        search_enabled = bool(search_value)
        network_enabled = bool(enabled_value) or search_enabled or bool(allowed) or bool(denied)

        object.__setattr__(self, "enabled", network_enabled)
        object.__setattr__(self, "search", search_enabled)
        object.__setattr__(self, "allowed_hosts", allowed)
        object.__setattr__(self, "denied_hosts", denied)

    @classmethod
    def disabled(cls) -> "NetworkPolicy":
        return cls(False)

    @classmethod
    def from_any(cls, value: "NetworkPolicy | Mapping[str, Any] | bool | None") -> "NetworkPolicy":
        if isinstance(value, cls):
            return value
        if value is None:
            return cls.disabled()
        if isinstance(value, Mapping):
            return cls(value)
        return cls(bool(value))

    @property
    def allow_network(self) -> bool:
        return self.enabled

    @property
    def allow_search(self) -> bool:
        return self.search

    def provider_flags(self, provider: str | object | None = None) -> dict[str, Any]:
        """Return only provider flags v1 knows how to map."""

        provider_name = _provider_name(provider)
        flags: dict[str, Any] = {}
        if "codex" in provider_name and self.search:
            flags["search"] = True
        return flags

    def to_provider_flags(self, provider: str | object | None = None) -> dict[str, Any]:
        return self.provider_flags(provider)

    def unsupported_diagnostics(self, provider: str | object | None = None) -> tuple[Diagnostic, ...]:
        provider_name = _provider_name(provider)
        diagnostics: list[Diagnostic] = []
        if self.allowed_hosts:
            diagnostics.append(
                Diagnostic.error(
                    code="policy.network.host_allowlist_unsupported",
                    message="Host allowlists are not supported by Accentor v1 network policy.",
                    source="dispatch.policy.network",
                    hint="Use a provider-side sandbox or remove host allowlists for v1.",
                    details={"provider": provider_name, "allowed_hosts": list(self.allowed_hosts)},
                )
            )
        if self.denied_hosts:
            diagnostics.append(
                Diagnostic.error(
                    code="policy.network.host_denylist_unsupported",
                    message="Host denylists are not supported by Accentor v1 network policy.",
                    source="dispatch.policy.network",
                    hint="Use a provider-side sandbox or remove host denylists for v1.",
                    details={"provider": provider_name, "denied_hosts": list(self.denied_hosts)},
                )
            )
        return tuple(diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "search": self.search,
            "allowed_hosts": list(self.allowed_hosts),
            "denied_hosts": list(self.denied_hosts),
        }


__all__ = ["NetworkPolicy"]
