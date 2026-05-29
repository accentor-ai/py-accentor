from __future__ import annotations

"""Unsupported task mutation-history stubs for v1."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskMutation:
    """Placeholder for future versioned task evolution."""

    description: str | None = None

    def apply(self, task: Any) -> Any:
        raise NotImplementedError("Task mutations are not supported in Accentor v1")


__all__ = ["TaskMutation"]
