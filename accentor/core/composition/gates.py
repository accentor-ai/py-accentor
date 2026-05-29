from __future__ import annotations

"""Extraction and validation gates for stage/workflow boundaries."""

import math
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable

from accentor.core.task.diagnostics import Diagnostic
from accentor.core.task.events import TaskEvent
from accentor.core.task.results import ArtifactReference, TaskResult
from accentor.evaluate.expose import (
    CustomExtractor,
    ExtractionContext,
    ExtractionResult,
    Extractor,
    JsonExtractor,
)
from accentor.evaluate.validation import ValidationContext, ValidationResult
from accentor.record.artifacts.store import ArtifactStore


ValidatorLike = Any
ExtractorLike = Extractor | Callable[..., ExtractionResult | Any]


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("gate report values must not contain non-finite floats")
        return value
    if isinstance(value, (Path, os.PathLike)):
        return os.fspath(value)
    if isinstance(value, Enum):
        return _json_ready(value.value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=repr)]
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return repr(value)


def _mapping_proxy(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _diagnostic_tuple(items: Sequence[Diagnostic | Mapping[str, Any]] | None) -> tuple[Diagnostic, ...]:
    if items is None:
        return ()
    diagnostics: list[Diagnostic] = []
    for item in items:
        if isinstance(item, Diagnostic):
            diagnostics.append(item)
        elif isinstance(item, Mapping):
            diagnostics.append(Diagnostic(**item))
        else:
            raise TypeError("diagnostics must contain Diagnostic objects or diagnostic mappings")
    return tuple(diagnostics)


def _artifact_tuple(items: Sequence[ArtifactReference] | None) -> tuple[ArtifactReference, ...]:
    return tuple(items or ())


def _message_tuple(messages: Any) -> tuple[str, ...]:
    if messages is None:
        return ()
    if isinstance(messages, str):
        return (messages,) if messages else ()
    if isinstance(messages, bytes):
        text = messages.decode("utf-8", errors="replace")
        return (text,) if text else ()
    try:
        return tuple(str(message) for message in messages if str(message))
    except TypeError:
        return (str(messages),) if str(messages) else ()


def _validator_name(validator: Any) -> str:
    if validator is None:
        return "validator"
    if isinstance(validator, str):
        return validator
    if isinstance(validator, type):
        return validator.__name__
    name = getattr(validator, "__name__", None)
    if name:
        return str(name)
    return validator.__class__.__name__


def _normalize_validators(validators: Iterable[ValidatorLike] | ValidatorLike | None) -> tuple[ValidatorLike, ...]:
    if validators is None:
        return ()
    if isinstance(validators, (str, bytes)) or callable(validators) or hasattr(validators, "validate"):
        return (validators,)
    return tuple(validators)


def _run_validator(
    validator: ValidatorLike,
    candidate: Any,
    context: ValidationContext,
) -> ValidationResult:
    validate = getattr(validator, "validate", None)
    if callable(validate):
        outcome = validate(candidate, context)
    else:
        outcome = validator(candidate)

    if isinstance(outcome, ValidationResult):
        return outcome

    name = _validator_name(validator)
    if isinstance(outcome, bool):
        if outcome:
            return ValidationResult.success(validator=name)
        return ValidationResult.failure("Validator returned False.", validator=name)

    messages = _message_tuple(outcome)
    if messages:
        return ValidationResult.failure(messages, validator=name)
    return ValidationResult.success(validator=name)


def _result_requires_parsed_json(result: ValidationResult) -> bool:
    return result.parsed_json_required or any(_result_requires_parsed_json(child) for child in result.children)


def _validation_result_payload(result: ValidationResult) -> dict[str, Any]:
    payload = result.to_dict()
    payload["parsed_json_required"] = _result_requires_parsed_json(result)
    return payload


def _blocking_extraction_diagnostics(extraction: ExtractionResult) -> tuple[Diagnostic, ...]:
    return tuple(
        diagnostic
        for diagnostic in extraction.diagnostics
        if diagnostic.severity in {"error", "critical"}
    )


def _selected_output(
    extraction: ExtractionResult,
    validation_results: Sequence[ValidationResult],
) -> tuple[Any, bool]:
    parsed_required = any(_result_requires_parsed_json(result) for result in validation_results)
    if parsed_required and extraction.parsed_available:
        return extraction.parsed_candidate, True
    return extraction.raw_candidate, False


def _make_extraction_context(
    context: ExtractionContext | Mapping[str, Any] | None,
    *,
    artifact_root: str | os.PathLike[str] | None = None,
    artifact_store: Any = None,
    metadata: Mapping[str, Any] | None = None,
) -> ExtractionContext:
    merged_metadata: dict[str, Any] = {}
    if isinstance(context, ExtractionContext):
        merged_metadata.update(context.metadata)
        merged_metadata.update(metadata or {})
        return ExtractionContext(
            raw=context.raw,
            parsed=context.parsed,
            has_parsed=context.has_parsed,
            source=context.source,
            artifact_root=artifact_root if artifact_root is not None else context.artifact_root,
            artifact_store=artifact_store if artifact_store is not None else context.artifact_store,
            path=context.path,
            artifact_name=context.artifact_name,
            diagnostics=context.diagnostics,
            metadata=merged_metadata,
        )
    if isinstance(context, Mapping):
        merged_metadata.update(context)
    elif context is not None:
        raise TypeError("extraction context must be an ExtractionContext, mapping, or None")
    merged_metadata.update(metadata or {})
    return ExtractionContext(
        artifact_root=artifact_root,
        artifact_store=artifact_store,
        metadata=merged_metadata,
    )


def _extract_candidate(
    candidate: Any,
    *,
    extractor: ExtractorLike | None,
    context: ExtractionContext,
) -> ExtractionResult:
    if isinstance(candidate, ExtractionResult):
        return candidate

    selected_extractor: ExtractorLike = extractor or JsonExtractor()
    extract = getattr(selected_extractor, "extract", None)
    if callable(extract):
        result = extract(candidate, context)
    elif callable(selected_extractor):
        result = CustomExtractor(selected_extractor).extract(candidate, context)
    else:
        raise TypeError("extractor must expose extract(candidate, context) or be callable")

    if isinstance(result, ExtractionResult):
        return result
    return ExtractionResult(raw=result, source=_validator_name(selected_extractor))


def _validation_context(
    extraction: ExtractionResult,
    extraction_context: ExtractionContext,
    *,
    attempt_index: int,
    metadata: Mapping[str, Any] | None = None,
) -> ValidationContext:
    merged_metadata = {
        **dict(extraction.metadata),
        **dict(extraction_context.metadata),
        **dict(metadata or {}),
        "attempt_index": attempt_index,
    }
    return ValidationContext(
        raw_candidate=extraction.raw,
        raw_text=extraction.raw_text,
        parsed_candidate=extraction.parsed if extraction.has_parsed else None,
        parsed_available=extraction.has_parsed,
        artifact_root=extraction_context.artifact_root,
        artifact_store=extraction_context.artifact_store,
        metadata=merged_metadata,
        diagnostics=extraction.diagnostics,
    )


@dataclass(frozen=True, slots=True)
class GateAttempt:
    """Extraction plus validation state for one candidate attempt."""

    attempt_index: int
    extraction: ExtractionResult
    validation_results: tuple[ValidationResult, ...] = field(default_factory=tuple)
    ok: bool = False
    output: Any = None
    parsed_output_selected: bool = False
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if isinstance(self.attempt_index, bool) or not isinstance(self.attempt_index, int):
            raise TypeError("attempt_index must be an int")
        if self.attempt_index < 0:
            raise ValueError("attempt_index must be non-negative")
        object.__setattr__(self, "validation_results", tuple(self.validation_results))
        object.__setattr__(self, "diagnostics", _diagnostic_tuple(self.diagnostics))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def raw_output(self) -> Any:
        return self.extraction.raw_candidate

    @property
    def parsed_output(self) -> Any:
        return self.extraction.parsed_candidate

    @property
    def validation_count(self) -> int:
        return len(self.validation_results)

    @property
    def passed_validation_count(self) -> int:
        return sum(1 for result in self.validation_results if result.ok)

    @property
    def parsed_json_required(self) -> bool:
        return any(_result_requires_parsed_json(result) for result in self.validation_results)

    @property
    def failed_validation_results(self) -> tuple[ValidationResult, ...]:
        return tuple(result for result in self.validation_results if not result.ok)

    @property
    def remediation_feedback(self) -> tuple[ValidationResult, ...]:
        return self.failed_validation_results

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_index": self.attempt_index,
            "ok": self.ok,
            "output": _json_ready(self.output),
            "raw_output": _json_ready(self.raw_output),
            "parsed_output": _json_ready(self.parsed_output) if self.extraction.parsed_available else None,
            "parsed_available": self.extraction.parsed_available,
            "parsed_output_selected": self.parsed_output_selected,
            "extraction": self.extraction.to_dict(),
            "validation": {
                "ok": self.ok,
                "results": [_validation_result_payload(result) for result in self.validation_results],
                "failure_count": len(self.failed_validation_results),
                "passed_count": self.passed_validation_count,
                "parsed_json_required": self.parsed_json_required,
            },
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "metadata": _json_ready(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class GateReport:
    """JSON-stable validation pipeline report across one or more attempts."""

    ok: bool
    output: Any = None
    best_output: Any = None
    attempts: tuple[GateAttempt, ...] = field(default_factory=tuple)
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    events: tuple[TaskEvent, ...] = field(default_factory=tuple)
    artifacts: tuple[ArtifactReference, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool):
            raise TypeError("ok must be a bool")
        object.__setattr__(self, "attempts", tuple(self.attempts))
        object.__setattr__(self, "diagnostics", _diagnostic_tuple(self.diagnostics))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "artifacts", _artifact_tuple(self.artifacts))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    @property
    def final_attempt(self) -> GateAttempt | None:
        return self.attempts[-1] if self.attempts else None

    @property
    def validation_results(self) -> tuple[ValidationResult, ...]:
        final = self.final_attempt
        return final.validation_results if final is not None else ()

    @property
    def remediation_feedback(self) -> tuple[ValidationResult, ...]:
        final = self.final_attempt
        if final is None or final.ok:
            return ()
        return final.remediation_feedback

    def to_task_result(self) -> TaskResult:
        return TaskResult(
            ok=self.ok,
            output=self.output if self.ok else None,
            best_output=self.best_output,
            diagnostics=self.diagnostics,
            attempt_count=self.attempt_count,
            events=self.events,
            artifacts=self.artifacts,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": _json_ready(self.output),
            "best_output": _json_ready(self.best_output),
            "attempt_count": self.attempt_count,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "validation_results": [
                _validation_result_payload(result)
                for result in self.validation_results
            ],
            "remediation_feedback": [
                _validation_result_payload(result)
                for result in self.remediation_feedback
            ],
            "events": [event.to_dict() for event in self.events],
            "artifacts": [_json_ready(artifact) for artifact in self.artifacts],
            "metadata": _json_ready(self.metadata),
        }


def validate_candidate(
    candidate: Any,
    validators: Iterable[ValidatorLike] | ValidatorLike | None = None,
    *,
    extractor: ExtractorLike | None = None,
    extraction_context: ExtractionContext | Mapping[str, Any] | None = None,
    attempt_index: int = 0,
    artifact_root: str | os.PathLike[str] | None = None,
    artifact_store: Any = None,
    metadata: Mapping[str, Any] | None = None,
) -> GateAttempt:
    """Extract and validate one candidate, preserving raw and parsed outputs."""

    selected_validators = _normalize_validators(validators)
    context = _make_extraction_context(
        extraction_context,
        artifact_root=artifact_root,
        artifact_store=artifact_store,
        metadata=metadata,
    )
    extraction = _extract_candidate(candidate, extractor=extractor, context=context)
    validation_context = _validation_context(
        extraction,
        context,
        attempt_index=attempt_index,
        metadata=metadata,
    )
    validation_results = tuple(
        _run_validator(validator, extraction.raw_candidate, validation_context)
        for validator in selected_validators
    )
    blocking_diagnostics = _blocking_extraction_diagnostics(extraction)
    ok = not blocking_diagnostics and all(result.ok for result in validation_results)
    output, parsed_selected = _selected_output(extraction, validation_results)
    diagnostics = (
        *extraction.diagnostics,
        *(diagnostic for result in validation_results for diagnostic in result.diagnostics),
    )

    return GateAttempt(
        attempt_index=attempt_index,
        extraction=extraction,
        validation_results=validation_results,
        ok=ok,
        output=output,
        parsed_output_selected=parsed_selected,
        diagnostics=diagnostics,
        metadata=metadata,
    )


def _candidate_iterator(candidates: Iterable[Any] | Any) -> Iterable[Any]:
    if isinstance(candidates, (str, bytes, Mapping, ExtractionResult)):
        return (candidates,)
    try:
        return iter(candidates)
    except TypeError:
        return (candidates,)


def _best_attempt(attempts: Sequence[GateAttempt]) -> GateAttempt | None:
    if not attempts:
        return None
    return max(
        attempts,
        key=lambda attempt: (
            attempt.ok,
            attempt.passed_validation_count,
            attempt.parsed_output_selected,
            attempt.extraction.parsed_available,
            attempt.attempt_index,
        ),
    )


def _pipeline_diagnostics(attempts: Sequence[GateAttempt], *, ok: bool) -> tuple[Diagnostic, ...]:
    if not attempts:
        return (
            Diagnostic.error(
                "validation.no_candidates",
                "Validation pipeline did not receive any candidates.",
                source="validation",
            ),
        )

    diagnostics: list[Diagnostic] = [
        diagnostic
        for attempt in attempts
        for diagnostic in attempt.diagnostics
    ]
    if ok:
        diagnostics.append(
            Diagnostic.info(
                "validation.accepted",
                "Output passed validation.",
                source="validation",
                details={"attempt_index": attempts[-1].attempt_index},
            )
        )
    else:
        diagnostics.append(
            Diagnostic.error(
                "validation.exhausted",
                "Validation failed for all available attempts.",
                source="validation",
                details={"attempt_count": len(attempts)},
            )
        )
    return tuple(diagnostics)


def _validation_event(
    report: GateReport,
    *,
    workflow: str | None = None,
    task: str | None = None,
    stage: str | None = None,
) -> TaskEvent:
    final = report.final_attempt
    return TaskEvent.validation_recorded(
        validation={
            "ok": report.ok,
            "attempt_count": report.attempt_count,
            "parsed_output_selected": bool(final and final.parsed_output_selected),
        },
        workflow=workflow,
        task=task,
        stage=stage,
        attempt=final.attempt_index if final is not None else None,
        status="accepted" if report.ok else "failed",
        diagnostics=report.diagnostics,
    )


def _artifact_store(
    *,
    artifact_store: Any = None,
    artifact_root: str | os.PathLike[str] | None = None,
) -> Any:
    if artifact_store is not None:
        return artifact_store
    if artifact_root is not None:
        return ArtifactStore(artifact_root)
    return None


def _write_report_artifacts(report: GateReport, store: Any) -> tuple[ArtifactReference, ...]:
    if store is None:
        return ()
    artifacts: list[ArtifactReference] = []
    write_json = getattr(store, "write_json", None)
    if not callable(write_json):
        raise TypeError("artifact_store must provide write_json(name, data)")
    for attempt in report.attempts:
        artifacts.append(
            write_json(
                f"validation_report_attempt_{attempt.attempt_index}.json",
                attempt.to_dict(),
            )
        )
    artifacts.append(write_json("validation_report.json", report.to_dict()))
    return tuple(artifacts)


def build_validation_report(
    candidates: Iterable[Any] | Any,
    validators: Iterable[ValidatorLike] | ValidatorLike | None = None,
    *,
    extractor: ExtractorLike | None = None,
    extraction_context: ExtractionContext | Mapping[str, Any] | None = None,
    max_attempts: int | None = None,
    artifact_root: str | os.PathLike[str] | None = None,
    artifact_store: Any = None,
    workflow: str | None = None,
    task: str | None = None,
    stage: str | None = None,
    write_reports: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> GateReport:
    """Run extraction/validation over attempts and return a gate report."""

    if max_attempts is not None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise TypeError("max_attempts must be an int or None")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

    store = _artifact_store(artifact_store=artifact_store, artifact_root=artifact_root)
    attempts: list[GateAttempt] = []
    for index, candidate in enumerate(_candidate_iterator(candidates)):
        if max_attempts is not None and index >= max_attempts:
            break
        attempt = validate_candidate(
            candidate,
            validators,
            extractor=extractor,
            extraction_context=extraction_context,
            attempt_index=index,
            artifact_root=artifact_root,
            artifact_store=store,
            metadata=metadata,
        )
        attempts.append(attempt)
        if attempt.ok:
            break

    accepted = attempts[-1] if attempts and attempts[-1].ok else None
    best = accepted or _best_attempt(attempts)
    output = accepted.output if accepted is not None else None
    best_output = best.output if best is not None else None
    ok = accepted is not None
    diagnostics = _pipeline_diagnostics(attempts, ok=ok)
    report = GateReport(
        ok=ok,
        output=output,
        best_output=best_output,
        attempts=tuple(attempts),
        diagnostics=diagnostics,
        metadata=metadata,
    )
    event = _validation_event(report, workflow=workflow, task=task, stage=stage)
    report = replace(report, events=(event,))
    if write_reports and store is not None:
        artifacts = _write_report_artifacts(report, store)
        report = replace(report, artifacts=artifacts)
    return report


def run_validation_pipeline(
    candidates: Iterable[Any] | Any,
    validators: Iterable[ValidatorLike] | ValidatorLike | None = None,
    **kwargs: Any,
) -> TaskResult:
    """Run the validation pipeline and return the user-facing TaskResult."""

    return build_validation_report(candidates, validators, **kwargs).to_task_result()


__all__ = [
    "GateAttempt",
    "GateReport",
    "build_validation_report",
    "run_validation_pipeline",
    "validate_candidate",
]
