from __future__ import annotations

"""Unsupported adapter manifest discovery stub for v1."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AdapterManifest:
    """Placeholder for future adapter manifest discovery."""

    source: str | None = None

    def discover(self) -> tuple[Any, ...]:
        raise NotImplementedError("Adapter manifest discovery is not supported in Accentor v1")

    def load(self) -> Any:
        raise NotImplementedError("Adapter manifest loading is not supported in Accentor v1")


__all__ = ["AdapterManifest"]
