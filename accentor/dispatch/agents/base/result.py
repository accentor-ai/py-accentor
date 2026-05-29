from __future__ import annotations

"""Provider-neutral result records for agent adapter runs."""

from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Mapping

from accentor.dispatch.agents.base.capabilities import AgentCapabilities


def _plain_value(value: Any) -> Any:
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _plain_value(to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return _plain_value(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True, init=False)
class AgentRunResult:
    """Structured outcome returned by every agent adapter."""

    ok: bool
    output: str
    elapsed_seconds: float
    diagnostics: list[Any]
    exit_code: int | None
    artifacts: list[Any]
    receipts: list[Any]
    capabilities: AgentCapabilities | None
    metadata: dict[str, Any]

    def __init__(
        self,
        output: str | None = None,
        *,
        final_message: str | None = None,
        ok: bool = True,
        elapsed_seconds: float | None = None,
        wall_time_seconds: float | None = None,
        diagnostics: list[Any] | tuple[Any, ...] | None = None,
        exit_code: int | None = None,
        exit_status: int | None = None,
        artifacts: list[Any] | tuple[Any, ...] | None = None,
        receipts: list[Any] | tuple[Any, ...] | None = None,
        capabilities: AgentCapabilities | Mapping[str, Any] | object | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if output is not None and final_message is not None and output != final_message:
            raise ValueError("output and final_message aliases must match when both are provided")
        if (
            elapsed_seconds is not None
            and wall_time_seconds is not None
            and elapsed_seconds != wall_time_seconds
        ):
            raise ValueError(
                "elapsed_seconds and wall_time_seconds aliases must match when both are provided"
            )
        if exit_code is not None and exit_status is not None and exit_code != exit_status:
            raise ValueError("exit_code and exit_status aliases must match when both are provided")

        output_value = output if output is not None else final_message
        elapsed_value = elapsed_seconds if elapsed_seconds is not None else wall_time_seconds
        exit_value = exit_code if exit_code is not None else exit_status
        capability_snapshot = (
            AgentCapabilities.from_any(capabilities) if capabilities is not None else None
        )

        object.__setattr__(self, "ok", bool(ok))
        object.__setattr__(self, "output", output_value or "")
        object.__setattr__(self, "elapsed_seconds", float(elapsed_value or 0.0))
        object.__setattr__(self, "diagnostics", list(diagnostics or ()))
        object.__setattr__(self, "exit_code", exit_value)
        object.__setattr__(self, "artifacts", list(artifacts or ()))
        object.__setattr__(self, "receipts", list(receipts or ()))
        object.__setattr__(self, "capabilities", capability_snapshot)
        object.__setattr__(self, "metadata", dict(metadata or {}))

    @property
    def final_message(self) -> str:
        return self.output

    @property
    def wall_time_seconds(self) -> float:
        return self.elapsed_seconds

    @property
    def exit_status(self) -> int | None:
        return self.exit_code

    @classmethod
    def failure(
        cls,
        message: str,
        *,
        code: str = "agent.run_failed",
        elapsed_seconds: float = 0.0,
        exit_code: int | None = None,
        diagnostics: list[Any] | tuple[Any, ...] | None = None,
        capabilities: AgentCapabilities | Mapping[str, Any] | object | None = None,
    ) -> "AgentRunResult":
        diagnostic = {
            "code": code,
            "message": message,
            "severity": "error",
            "source": "agent",
            "hint": None,
            "details": {},
        }
        return cls(
            ok=False,
            output="",
            elapsed_seconds=elapsed_seconds,
            exit_code=exit_code,
            diagnostics=[*(diagnostics or ()), diagnostic],
            capabilities=capabilities,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "final_message": self.final_message,
            "elapsed_seconds": self.elapsed_seconds,
            "wall_time_seconds": self.wall_time_seconds,
            "diagnostics": _plain_value(self.diagnostics),
            "exit_code": self.exit_code,
            "exit_status": self.exit_status,
            "artifacts": _plain_value(self.artifacts),
            "receipts": _plain_value(self.receipts),
            "capabilities": self.capabilities.to_dict() if self.capabilities else None,
            "metadata": _plain_value(self.metadata),
        }


__all__ = ["AgentRunResult"]
