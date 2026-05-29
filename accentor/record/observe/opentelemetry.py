from __future__ import annotations

"""Unsupported OpenTelemetry observation sink stub for v1."""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class OtelSink:
    """Placeholder for future OpenTelemetry observation export."""

    endpoint: str | None = None

    def emit(self, event: Mapping[str, Any]) -> None:
        raise NotImplementedError("OpenTelemetry observation sinks are not supported in Accentor v1")

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


OpenTelemetrySink = OtelSink

__all__ = ["OpenTelemetrySink", "OtelSink"]
