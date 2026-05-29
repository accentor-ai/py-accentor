from __future__ import annotations

"""Unsupported remote workspace backend stub for v1."""

from dataclasses import dataclass
from typing import Any

from accentor.dispatch.workspace.plans import WorkspacePlan


@dataclass(frozen=True, slots=True)
class RemoteWorkspaceBackend:
    """Placeholder for future remote sandbox managers."""

    endpoint: str | None = None

    def prepare(self, plan: WorkspacePlan) -> Any:
        raise NotImplementedError("Remote workspace backends are not supported in Accentor v1")

    stage = prepare


__all__ = ["RemoteWorkspaceBackend"]
