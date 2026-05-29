from __future__ import annotations

"""Unsupported routing-table API stub for v1."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from accentor.dispatch.routing.base import RoutingContext, RoutingDecision


@dataclass(frozen=True, slots=True)
class RoutingTable:
    """Placeholder for future YAML or table-backed routing."""

    source: str | Path | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> "RoutingTable":
        raise NotImplementedError("RoutingTable file loading is not supported in Accentor v1")

    def route(self, context: RoutingContext) -> RoutingDecision:
        raise NotImplementedError("RoutingTable routing is not supported in Accentor v1")


__all__ = ["RoutingTable"]
