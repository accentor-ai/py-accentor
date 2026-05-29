from __future__ import annotations

"""Deterministic intra-task routing helpers."""

import inspect
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable

from accentor.dispatch.routing.base import (
    RouteCandidate,
    RoutingContext,
    RoutingDecision,
    RoutingDiagnostic,
)


FRAMEWORK_INJECTED_PARAMETERS = frozenset({"ctx", "routed_context", "success_criteria"})
ROUTING_DECISIONS_ARTIFACT = "routing_decisions.jsonl"


@dataclass(frozen=True, slots=True)
class RoutingResolution:
    """Resolved route plus the selected and omitted candidate records."""

    context: RoutingContext
    decision: RoutingDecision
    selected_candidate: RouteCandidate | None = None
    omitted_candidates: tuple[RouteCandidate, ...] = ()
    diagnostics: tuple[RoutingDiagnostic, ...] = ()

    @property
    def ok(self) -> bool:
        return self.selected_candidate is not None and not any(
            diagnostic.severity in {"error", "critical"} for diagnostic in self.diagnostics
        )

    @property
    def selected(self) -> str | None:
        return self.selected_candidate.name if self.selected_candidate is not None else self.decision.selected

    @property
    def omitted(self) -> tuple[str, ...]:
        return tuple(candidate.name for candidate in self.omitted_candidates)


def _callable_name(value: Any) -> str:
    return str(getattr(value, "__name__", None) or getattr(value, "name", None) or type(value).__name__)


def _candidate_from_any(value: Any) -> RouteCandidate:
    if isinstance(value, RouteCandidate):
        return value
    if isinstance(value, Mapping):
        if "name" not in value:
            raise ValueError("route candidate mappings require a name")
        return RouteCandidate(
            name=str(value["name"]),
            context=value.get("context"),
            metadata=value.get("metadata") or {},
        )
    raise TypeError("route candidates must be RouteCandidate objects or mappings")


def normalize_route_candidates(candidates: Sequence[Any] | Any | None) -> tuple[RouteCandidate, ...]:
    """Normalize decorator route candidate declarations."""

    if candidates is None:
        return ()
    if isinstance(candidates, (RouteCandidate, Mapping)):
        raw_candidates = (candidates,)
    else:
        try:
            raw_candidates = tuple(candidates)
        except TypeError:
            raw_candidates = (candidates,)

    normalized = tuple(_candidate_from_any(candidate) for candidate in raw_candidates)
    names = [candidate.name for candidate in normalized]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError("duplicate route candidate name(s): " + ", ".join(duplicates))
    return normalized


def _fallback_input(args: Sequence[Any], kwargs: Mapping[str, Any]) -> dict[str, Any]:
    data = {f"arg{index}": value for index, value in enumerate(args)}
    data.update({str(key): value for key, value in kwargs.items() if str(key) not in FRAMEWORK_INJECTED_PARAMETERS})
    return data


def routing_input_for_call(
    function: Callable[..., Any],
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
    *,
    exclude: set[str] | frozenset[str] = FRAMEWORK_INJECTED_PARAMETERS,
) -> dict[str, Any]:
    """Return user-supplied stage inputs visible to the router."""

    try:
        signature = inspect.signature(function)
        bound = signature.bind_partial(*tuple(args), **dict(kwargs))
    except (TypeError, ValueError):
        return _fallback_input(args, kwargs)

    data: dict[str, Any] = {}
    for name, value in bound.arguments.items():
        parameter = signature.parameters.get(name)
        if name in exclude:
            continue
        if parameter is not None and parameter.kind is inspect.Parameter.VAR_KEYWORD:
            if isinstance(value, Mapping):
                data.update({str(key): item for key, item in value.items() if str(key) not in exclude})
            continue
        data[name] = value
    return data


def declares_parameter(function: Callable[..., Any], parameter_name: str) -> bool:
    """Return true when the wrapped function explicitly declares a parameter."""

    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return False
    return parameter_name in signature.parameters


def resolve_route(
    router: Callable[[RoutingContext], Any],
    *,
    stage_name: str,
    function: Callable[..., Any],
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
    route_candidates: Sequence[Any] | Any,
    run_id: str | None = None,
) -> RoutingResolution:
    """Run a deterministic router and resolve its decision to a candidate."""

    candidates = normalize_route_candidates(route_candidates)
    candidate_by_name = {candidate.name: candidate for candidate in candidates}
    context = RoutingContext(
        stage=stage_name,
        input=routing_input_for_call(function, args, kwargs),
        candidate_names=tuple(candidate_by_name),
        metadata={
            "router": _callable_name(router),
            **({"run_id": run_id} if run_id is not None else {}),
        },
    )

    diagnostics: list[RoutingDiagnostic] = []
    try:
        decision = RoutingDecision.from_any(router(context))
    except Exception as exc:  # noqa: BLE001 - router failures are routed diagnostics.
        decision = RoutingDecision(selected=None)
        diagnostics.append(
            RoutingDiagnostic(
                code="routing.exception",
                message=f"Router {_callable_name(router)!r} raised {type(exc).__name__}: {exc}",
                details={"exception_type": type(exc).__name__},
            )
        )

    diagnostics.extend(decision.diagnostics)
    selected = candidate_by_name.get(decision.selected or "")
    omitted = tuple(candidate for candidate in candidates if candidate is not selected)
    if selected is None:
        diagnostics.append(
            RoutingDiagnostic(
                code="routing.no_match",
                message="Router did not select a configured route candidate.",
                details={
                    "selected": decision.selected,
                    "candidate_names": list(context.candidate_names),
                },
            )
        )

    return RoutingResolution(
        context=context,
        decision=decision,
        selected_candidate=selected,
        omitted_candidates=omitted,
        diagnostics=tuple(diagnostics),
    )


def kwargs_with_routed_context(
    function: Callable[..., Any],
    kwargs: Mapping[str, Any],
    resolution: RoutingResolution,
) -> dict[str, Any]:
    """Inject only the selected context when the stage declares routed_context."""

    updated = dict(kwargs)
    if resolution.selected_candidate is not None and declares_parameter(function, "routed_context"):
        updated["routed_context"] = resolution.selected_candidate.context
    return updated


def routing_record(
    resolution: RoutingResolution,
    *,
    run_id: str,
    stage: str,
    task: str | None = None,
    workflow: str | None = None,
) -> dict[str, Any]:
    """Build the safe artifact/event payload for a routing decision."""

    decision = resolution.decision
    candidate_metadata = {}
    routed_candidates = list(resolution.omitted_candidates)
    if resolution.selected_candidate is not None:
        routed_candidates.append(resolution.selected_candidate)
    for name, metadata in ((candidate.name, candidate.metadata) for candidate in routed_candidates):
        if metadata:
            candidate_metadata[name] = RouteCandidate(name=name, context=None, metadata=metadata).to_dict(
                include_context=False
            )["metadata"]

    metadata = {
        "router": resolution.context.metadata.get("router"),
        "input_keys": sorted(resolution.context.input),
        **decision.to_dict()["metadata"],
    }
    if candidate_metadata:
        metadata["candidate_metadata"] = candidate_metadata

    return {
        "run_id": run_id,
        "task_id": task,
        "workflow": workflow,
        "stage": stage,
        "selected": decision.selected,
        "selected_candidate": resolution.selected_candidate.name if resolution.selected_candidate is not None else None,
        "omitted": list(resolution.omitted),
        "omitted_candidates": list(resolution.omitted),
        "candidates": list(resolution.context.candidate_names),
        "rationale": decision.rationale,
        "confidence": decision.confidence,
        "diagnostics": [diagnostic.to_dict() for diagnostic in resolution.diagnostics],
        "metadata": metadata,
    }


def append_routing_record(
    artifact_store: Any,
    record: Mapping[str, Any],
    *,
    artifact_name: str = ROUTING_DECISIONS_ARTIFACT,
    append: bool = True,
) -> Any:
    """Append one routing decision to the invocation-local JSONL artifact."""

    mode = "a" if append else "w"
    with artifact_store.open(artifact_name, mode, encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record), allow_nan=False, sort_keys=True))
        handle.write("\n")
    return artifact_store.record(artifact_name, content_type="application/x-ndjson")


__all__ = [
    "FRAMEWORK_INJECTED_PARAMETERS",
    "ROUTING_DECISIONS_ARTIFACT",
    "RoutingResolution",
    "append_routing_record",
    "declares_parameter",
    "kwargs_with_routed_context",
    "normalize_route_candidates",
    "resolve_route",
    "routing_input_for_call",
    "routing_record",
]
