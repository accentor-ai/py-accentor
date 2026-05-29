from __future__ import annotations

"""Unsupported parallel composition stub for v1."""

from typing import Any


def parallel(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("Parallel composition is not supported in Accentor v1")


__all__ = ["parallel"]
