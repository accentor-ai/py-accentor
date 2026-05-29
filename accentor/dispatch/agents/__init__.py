from __future__ import annotations

"""Agent adapter contracts and provider namespaces."""

from accentor.dispatch.agents.base import (
    AgentAdapter,
    AgentCapabilities,
    AgentRequest,
    AgentRunResult,
    PersistentAgentAdapter,
)

__all__ = [
    "AgentAdapter",
    "AgentCapabilities",
    "AgentRequest",
    "AgentRunResult",
    "PersistentAgentAdapter",
]
