from __future__ import annotations

"""Unsupported third-party routing adapter stubs for v1."""

from dataclasses import dataclass
from typing import Any

from accentor.dispatch.routing.base import RoutingContext, RoutingDecision


@dataclass(frozen=True, slots=True)
class ClassifierRouter:
    """Placeholder for future classifier-backed routing."""

    name: str = "classifier-router"

    def route(self, context: RoutingContext) -> RoutingDecision:
        raise NotImplementedError("ClassifierRouter is not supported in Accentor v1")

    def __call__(self, context: RoutingContext) -> RoutingDecision:
        return self.route(context)


__all__ = ["ClassifierRouter"]
