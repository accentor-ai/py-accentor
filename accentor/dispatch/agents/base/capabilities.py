from __future__ import annotations

"""Provider-neutral agent capability records."""

from dataclasses import dataclass
from typing import Any, Mapping


_CAPABILITY_FIELDS = {
    "supports_files",
    "supports_shell",
    "supports_sandbox",
    "supports_workspace_write",
    "supports_persistence",
    "supports_resume",
    "supports_streaming",
    "supports_tool_receipts",
}

_CAPABILITY_ALIASES = {
    "files": "supports_files",
    "shell": "supports_shell",
    "sandbox": "supports_sandbox",
    "workspace_write": "supports_workspace_write",
    "persistence": "supports_persistence",
    "persistent_sessions": "supports_persistence",
    "resume": "supports_resume",
    "streaming": "supports_streaming",
    "tool_receipts": "supports_tool_receipts",
}


def _first_flag(*values: bool | None) -> bool:
    for value in values:
        if value is not None:
            return bool(value)
    return False


@dataclass(frozen=True, slots=True, init=False)
class AgentCapabilities:
    """Frozen snapshot of capabilities exposed by an agent adapter."""

    supports_files: bool
    supports_shell: bool
    supports_sandbox: bool
    supports_workspace_write: bool
    supports_persistence: bool
    supports_resume: bool
    supports_streaming: bool
    supports_tool_receipts: bool

    def __init__(
        self,
        *,
        supports_files: bool | None = None,
        supports_shell: bool | None = None,
        supports_sandbox: bool | None = None,
        supports_workspace_write: bool | None = None,
        supports_persistence: bool | None = None,
        supports_resume: bool | None = None,
        supports_streaming: bool | None = None,
        supports_tool_receipts: bool | None = None,
        files: bool | None = None,
        shell: bool | None = None,
        sandbox: bool | None = None,
        workspace_write: bool | None = None,
        persistence: bool | None = None,
        persistent_sessions: bool | None = None,
        resume: bool | None = None,
        streaming: bool | None = None,
        tool_receipts: bool | None = None,
    ) -> None:
        object.__setattr__(self, "supports_files", _first_flag(supports_files, files))
        object.__setattr__(self, "supports_shell", _first_flag(supports_shell, shell))
        object.__setattr__(self, "supports_sandbox", _first_flag(supports_sandbox, sandbox))
        object.__setattr__(
            self,
            "supports_workspace_write",
            _first_flag(supports_workspace_write, workspace_write),
        )
        object.__setattr__(
            self,
            "supports_persistence",
            _first_flag(supports_persistence, persistent_sessions, persistence),
        )
        object.__setattr__(self, "supports_resume", _first_flag(supports_resume, resume))
        object.__setattr__(self, "supports_streaming", _first_flag(supports_streaming, streaming))
        object.__setattr__(
            self,
            "supports_tool_receipts",
            _first_flag(supports_tool_receipts, tool_receipts),
        )

    @property
    def files(self) -> bool:
        return self.supports_files

    @property
    def shell(self) -> bool:
        return self.supports_shell

    @property
    def sandbox(self) -> bool:
        return self.supports_sandbox

    @property
    def workspace_write(self) -> bool:
        return self.supports_workspace_write

    @property
    def persistence(self) -> bool:
        return self.supports_persistence

    @property
    def persistent_sessions(self) -> bool:
        return self.supports_persistence

    @property
    def resume(self) -> bool:
        return self.supports_resume

    @property
    def streaming(self) -> bool:
        return self.supports_streaming

    @property
    def tool_receipts(self) -> bool:
        return self.supports_tool_receipts

    @classmethod
    def from_any(cls, value: object | None) -> "AgentCapabilities":
        """Build a frozen snapshot from another capability-shaped object."""

        if value is None:
            return cls()
        if isinstance(value, cls):
            return value.snapshot()
        if isinstance(value, Mapping):
            kwargs = {
                str(key): item
                for key, item in value.items()
                if str(key) in _CAPABILITY_FIELDS or str(key) in _CAPABILITY_ALIASES
            }
            return cls(**kwargs)

        kwargs: dict[str, Any] = {}
        for name in _CAPABILITY_FIELDS | set(_CAPABILITY_ALIASES):
            if hasattr(value, name):
                kwargs[name] = getattr(value, name)
        return cls(**kwargs)

    def snapshot(self) -> "AgentCapabilities":
        return AgentCapabilities(**self.to_dict())

    def to_dict(self) -> dict[str, bool]:
        return {
            "supports_files": self.supports_files,
            "supports_shell": self.supports_shell,
            "supports_sandbox": self.supports_sandbox,
            "supports_workspace_write": self.supports_workspace_write,
            "supports_persistence": self.supports_persistence,
            "supports_resume": self.supports_resume,
            "supports_streaming": self.supports_streaming,
            "supports_tool_receipts": self.supports_tool_receipts,
            "persistent_sessions": self.supports_persistence,
            "workspace_write": self.supports_workspace_write,
        }


__all__ = ["AgentCapabilities"]
