from __future__ import annotations

"""Unsupported Docker workspace backend stub for v1."""

from dataclasses import dataclass
from typing import Any

from accentor.dispatch.workspace.plans import WorkspacePlan


@dataclass(frozen=True, slots=True)
class DockerWorkspaceBackend:
    """Placeholder for future Docker-backed workspaces."""

    image: str | None = None

    def prepare(self, plan: WorkspacePlan) -> Any:
        raise NotImplementedError("Docker workspace backends are not supported in Accentor v1")

    stage = prepare


__all__ = ["DockerWorkspaceBackend"]
