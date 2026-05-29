from __future__ import annotations

"""Unsupported object-store artifact backend stub for v1."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ObjectStoreBackend:
    """Placeholder for future cloud/object artifact storage."""

    bucket: str | None = None

    def put(self, name: str, data: bytes | str) -> Any:
        raise NotImplementedError("Object-store artifact backends are not supported in Accentor v1")

    def get(self, name: str) -> bytes:
        raise NotImplementedError("Object-store artifact backends are not supported in Accentor v1")


__all__ = ["ObjectStoreBackend"]
