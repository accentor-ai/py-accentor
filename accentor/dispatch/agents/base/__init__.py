from __future__ import annotations

"""Base agent adapter contracts."""

from accentor.dispatch.agents.base.adapter import AgentAdapter, PersistentAgentAdapter
from accentor.dispatch.agents.base.capabilities import AgentCapabilities
from accentor.dispatch.agents.base.request import AgentRequest
from accentor.dispatch.agents.base.result import AgentRunResult

__all__ = [
    "AgentAdapter",
    "AgentCapabilities",
    "AgentRequest",
    "AgentRunResult",
    "PersistentAgentAdapter",
]
