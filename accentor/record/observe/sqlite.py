from __future__ import annotations

"""Unsupported SQLite observation sink stub for v1."""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class SqliteSink:
    """Placeholder for future SQLite observation storage."""

    path: str | None = None

    def emit(self, event: Mapping[str, Any]) -> None:
        raise NotImplementedError("SQLite observation sinks are not supported in Accentor v1")

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


__all__ = ["SqliteSink"]
