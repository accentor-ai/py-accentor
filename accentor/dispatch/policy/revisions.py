from __future__ import annotations

"""Permission revision records for staged read grants and revocations."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from accentor.core.task.diagnostics import JsonValue, _normalize_json_value, _plain_json_value


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _string_tuple(values: Iterable[object] | object | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        return (str(values),)
    try:
        return tuple(str(value) for value in values)  # type: ignore[arg-type]
    except TypeError:
        return (str(values),)


def _normalize_metadata(value: Mapping[str, Any] | None) -> Mapping[str, JsonValue]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("revision metadata must be a mapping")
    return _normalize_json_value(value)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True, init=False)
class PermissionRevision:
    """Auditable permission mutation record."""

    action: str
    paths: tuple[str, ...]
    phase: str | None
    reason: str | None
    revision_id: str | None
    timestamp: str
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __init__(
        self,
        action: str,
        paths: Iterable[object] | object | None = None,
        *,
        phase: str | None = None,
        reason: str | None = None,
        revision_id: str | None = None,
        timestamp: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not action:
            raise ValueError("permission revision action is required")
        normalized_paths = _string_tuple(paths)
        if not normalized_paths:
            raise ValueError("permission revision paths are required")

        object.__setattr__(self, "action", action)
        object.__setattr__(self, "paths", normalized_paths)
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "revision_id", revision_id)
        object.__setattr__(self, "timestamp", timestamp or _utc_now_iso())
        object.__setattr__(self, "metadata", _normalize_metadata(metadata))

    def apply(self, permission_set: object) -> object:
        """Apply this revision to a PermissionSet-like object."""

        if not hasattr(permission_set, "with_revision"):
            raise TypeError("permission_set must provide with_revision(revision)")
        return permission_set.with_revision(self)  # type: ignore[no-any-return, attr-defined]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "paths": list(self.paths),
            "phase": self.phase,
            "reason": self.reason,
            "revision_id": self.revision_id,
            "timestamp": self.timestamp,
            "metadata": _plain_json_value(self.metadata),
        }


class GrantRead(PermissionRevision):
    """Grant read access for a later phase."""

    def __init__(
        self,
        paths: Iterable[object] | object | None = None,
        *,
        phase: str | None = None,
        reason: str | None = None,
        revision_id: str | None = None,
        timestamp: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            action="grant_read",
            paths=paths,
            phase=phase,
            reason=reason,
            revision_id=revision_id,
            timestamp=timestamp,
            metadata=metadata,
        )


class RevokeRead(PermissionRevision):
    """Remove read access before a later phase."""

    def __init__(
        self,
        paths: Iterable[object] | object | None = None,
        *,
        phase: str | None = None,
        reason: str | None = None,
        revision_id: str | None = None,
        timestamp: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            action="revoke_read",
            paths=paths,
            phase=phase,
            reason=reason,
            revision_id=revision_id,
            timestamp=timestamp,
            metadata=metadata,
        )


__all__ = ["GrantRead", "PermissionRevision", "RevokeRead"]
