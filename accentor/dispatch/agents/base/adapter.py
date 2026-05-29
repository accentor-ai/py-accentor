from __future__ import annotations

"""Base adapter protocol shared by all agent providers."""

from dataclasses import dataclass, field
from typing import Protocol

from accentor.dispatch.agents.base.capabilities import AgentCapabilities
from accentor.dispatch.agents.base.request import AgentRequest
from accentor.dispatch.agents.base.result import AgentRunResult


class AgentAdapter(Protocol):
    """Structural contract implemented by provider adapters."""

    name: str
    capabilities: AgentCapabilities

    def run(self, request: AgentRequest) -> AgentRunResult:
        """Run one request and return a structured result."""
        ...

    def close(self) -> None:
        """Optional resource cleanup hook for adapters that need one."""


@dataclass(frozen=True, slots=True)
class PersistentAgentAdapter:
    """Unsupported v1 persistence placeholder.

    Persistent adapter behavior needs provider-specific continuation semantics,
    so v1 keeps the name importable without pretending persistence works.
    """

    name: str = "persistent-agent-adapter"
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)

    def run(self, request: AgentRequest) -> AgentRunResult:
        raise NotImplementedError("PersistentAgentAdapter is not supported in v1")

    def close(self) -> None:
        return None


__all__ = ["AgentAdapter", "PersistentAgentAdapter"]
