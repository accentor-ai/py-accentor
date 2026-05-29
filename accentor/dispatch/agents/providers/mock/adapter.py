from __future__ import annotations

"""Deterministic mock implementation of the agent adapter protocol."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from accentor.dispatch.agents.base import AgentCapabilities, AgentRequest, AgentRunResult


DiagnosticLike: TypeAlias = Mapping[str, Any] | object


def _diagnostic(
    *,
    code: str,
    message: str,
    severity: str = "error",
    hint: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "source": "mock_agent",
        "hint": hint,
        "details": dict(details or {}),
    }


def _response_metadata(
    *,
    adapter_name: str,
    response_index: int | None,
    session: str | None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "adapter": adapter_name,
        "response_index": response_index,
    }
    if session is not None:
        metadata["session"] = session
    metadata.update(dict(extra or {}))
    return metadata


@dataclass(frozen=True, slots=True)
class ScriptedFailure:
    """Fixture object that becomes a structured failed agent result."""

    message: str = "Scripted mock agent failure."
    code: str = "mock.scripted_failure"
    severity: str = "error"
    output: str = ""
    exit_code: int | None = 1
    diagnostics: Sequence[DiagnosticLike] = field(default_factory=tuple)
    artifacts: Sequence[Any] = field(default_factory=tuple)
    receipts: Sequence[Any] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_result(
        self,
        *,
        capabilities: AgentCapabilities,
        elapsed_seconds: float = 0.0,
        metadata: Mapping[str, Any] | None = None,
        receipts: Sequence[Any] | None = None,
    ) -> AgentRunResult:
        result_metadata = dict(metadata or {})
        result_metadata.update(dict(self.metadata))
        return AgentRunResult(
            ok=False,
            output=self.output,
            elapsed_seconds=elapsed_seconds,
            exit_code=self.exit_code,
            diagnostics=[
                *self.diagnostics,
                _diagnostic(
                    code=self.code,
                    message=self.message,
                    severity=self.severity,
                ),
            ],
            artifacts=list(self.artifacts),
            receipts=[*(receipts or ()), *self.receipts],
            capabilities=capabilities,
            metadata=result_metadata,
        )


MockAgentFailure = ScriptedFailure
ResponseLike: TypeAlias = str | Mapping[str, Any] | AgentRunResult | ScriptedFailure | BaseException
MockResponse: TypeAlias = ResponseLike


def mock_failure(
    message: str = "Scripted mock agent failure.",
    *,
    code: str = "mock.scripted_failure",
    severity: str = "error",
    output: str = "",
    exit_code: int | None = 1,
    diagnostics: Sequence[DiagnosticLike] | None = None,
    artifacts: Sequence[Any] | None = None,
    receipts: Sequence[Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ScriptedFailure:
    """Return a scripted failure object for use in ``MockAgent(responses=[...])``."""

    return ScriptedFailure(
        message=message,
        code=code,
        severity=severity,
        output=output,
        exit_code=exit_code,
        diagnostics=tuple(diagnostics or ()),
        artifacts=tuple(artifacts or ()),
        receipts=tuple(receipts or ()),
        metadata=dict(metadata or {}),
    )


class MockAgent:
    """A deterministic adapter for tests that need agent-shaped dispatch.

    The mock consumes scripted responses in order. It does not inspect files,
    execute commands, infer repairs, or claim that a text response changed a
    workspace.
    """

    def __init__(
        self,
        responses: Iterable[ResponseLike] | ResponseLike | None = None,
        *,
        name: str = "MockAgent",
        capabilities: AgentCapabilities | Mapping[str, Any] | object | None = None,
        session: str | None = None,
        receipts: Sequence[Any] | None = None,
    ) -> None:
        if session is not None and session != "persistent":
            raise ValueError("MockAgent session must be None or session='persistent'")

        if responses is None:
            response_list: list[ResponseLike] = []
        elif isinstance(responses, (str, Mapping, AgentRunResult, ScriptedFailure, BaseException)):
            response_list = [responses]
        else:
            response_list = list(responses)

        self.name = name
        self.session = session
        self.capabilities = (
            AgentCapabilities.from_any(capabilities)
            if capabilities is not None
            else AgentCapabilities(
                supports_persistence=session == "persistent",
                supports_tool_receipts=bool(receipts),
            )
        )
        self.responses = response_list
        self._next_response_index = 0
        self._receipts = list(receipts or ())
        self.requests: list[AgentRequest] = []

    @property
    def exhausted(self) -> bool:
        return self._next_response_index >= len(self.responses)

    @property
    def consumed_count(self) -> int:
        return self._next_response_index

    @property
    def run_count(self) -> int:
        return self._next_response_index

    @property
    def remaining_responses(self) -> int:
        return max(len(self.responses) - self._next_response_index, 0)

    def run(self, request: AgentRequest) -> AgentRunResult:
        self.requests.append(request)
        if self.exhausted:
            return self._exhausted_result()

        response_index = self._next_response_index
        response = self.responses[response_index]
        self._next_response_index += 1
        return self._coerce_response(response, response_index=response_index)

    def close(self) -> None:
        return None

    def _coerce_response(
        self,
        response: ResponseLike,
        *,
        response_index: int,
    ) -> AgentRunResult:
        metadata = _response_metadata(
            adapter_name=self.name,
            response_index=response_index,
            session=self.session,
        )

        if isinstance(response, AgentRunResult):
            return self._copy_result(response, response_index=response_index)

        if isinstance(response, ScriptedFailure):
            metadata["scripted_failure"] = True
            return response.to_result(
                capabilities=self.capabilities,
                metadata=metadata,
                receipts=self._receipts,
            )

        if isinstance(response, BaseException):
            return AgentRunResult(
                ok=False,
                output="",
                elapsed_seconds=0.0,
                exit_code=1,
                diagnostics=[
                    _diagnostic(
                        code="mock.scripted_exception",
                        message=str(response) or type(response).__name__,
                        details={"exception_type": type(response).__name__},
                    )
                ],
                capabilities=self.capabilities,
                metadata=metadata,
            )

        if isinstance(response, Mapping):
            payload = dict(response)
            response_metadata = dict(payload.get("metadata") or {})
            payload["metadata"] = _response_metadata(
                adapter_name=self.name,
                response_index=response_index,
                session=self.session,
                extra=response_metadata,
            )
            payload.setdefault("elapsed_seconds", 0.0)
            payload.setdefault("capabilities", self.capabilities)
            payload.setdefault("receipts", list(self._receipts))
            return AgentRunResult(**payload)

        return AgentRunResult(
            ok=True,
            output=str(response),
            elapsed_seconds=0.0,
            exit_code=0,
            diagnostics=[],
            receipts=list(self._receipts),
            capabilities=self.capabilities,
            metadata=metadata,
        )

    def _copy_result(
        self,
        result: AgentRunResult,
        *,
        response_index: int,
    ) -> AgentRunResult:
        metadata = _response_metadata(
            adapter_name=self.name,
            response_index=response_index,
            session=self.session,
            extra=result.metadata,
        )
        return AgentRunResult(
            ok=result.ok,
            output=result.output,
            elapsed_seconds=result.elapsed_seconds,
            diagnostics=list(result.diagnostics),
            exit_code=result.exit_code,
            artifacts=list(result.artifacts),
            receipts=[*self._receipts, *result.receipts],
            capabilities=result.capabilities or self.capabilities,
            metadata=metadata,
        )

    def _exhausted_result(self) -> AgentRunResult:
        metadata = _response_metadata(
            adapter_name=self.name,
            response_index=None,
            session=self.session,
            extra={"responses_total": len(self.responses)},
        )
        return AgentRunResult(
            ok=False,
            output="",
            elapsed_seconds=0.0,
            exit_code=1,
            diagnostics=[
                _diagnostic(
                    code="mock.responses_exhausted",
                    message="MockAgent has no scripted responses remaining.",
                    hint="Provide another response fixture or reduce the expected run count.",
                    details={
                        "response_count": len(self.responses),
                        "responses_total": len(self.responses),
                        "call_index": self._next_response_index,
                        "session": self.session,
                    },
                )
            ],
            capabilities=self.capabilities,
            metadata=metadata,
        )


__all__ = [
    "MockAgent",
    "MockAgentFailure",
    "MockResponse",
    "ResponseLike",
    "ScriptedFailure",
    "mock_failure",
]
