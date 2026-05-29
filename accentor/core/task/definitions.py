from __future__ import annotations

"""Task definition records and the v1 phase runner."""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from accentor.core.composition.gates import build_validation_report
from accentor.core.steps import Phase
from accentor.core.task.diagnostics import Diagnostic
from accentor.core.task.events import TaskEvent
from accentor.core.task.results import ArtifactReference, TaskResult
from accentor.dispatch.agents.base import AgentCapabilities, AgentRequest, AgentRunResult
from accentor.dispatch.workspace import LocalWorkspaceBackend, StagedWorkspace, WorkspacePlan
from accentor.record.artifacts import ArtifactRecord
from accentor.record.artifacts.store import ArtifactStore
from accentor.record.observe import JsonlSink, TaskObserver


PathInput = str | os.PathLike[str]


def _nonempty_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _json_ready(value: Any) -> Any:
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=repr)]
    return value


def _metadata(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    ready = _json_ready(dict(value or {}))
    if not isinstance(ready, dict):
        raise TypeError("metadata must serialize to a mapping")
    return MappingProxyType(ready)


def _artifact_to_dict(artifact: ArtifactReference) -> dict[str, Any]:
    if isinstance(artifact, ArtifactRecord):
        return artifact.to_dict()
    return dict(artifact)


def _coerce_diagnostics(items: Sequence[Any], *, source: str, default_code: str) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    for item in items:
        if isinstance(item, Diagnostic):
            diagnostics.append(item)
        elif isinstance(item, Mapping):
            diagnostics.append(Diagnostic(**item))
        else:
            to_dict = getattr(item, "to_dict", None)
            if callable(to_dict):
                payload = to_dict()
                if isinstance(payload, Mapping):
                    diagnostics.append(Diagnostic(**payload))
                    continue
            diagnostics.append(Diagnostic.error(default_code, str(item), source=source))
    return tuple(diagnostics)


def _agent_name(agent: Any) -> str:
    return str(getattr(agent, "name", None) or type(agent).__name__)


def _run_agent(agent: Any, request: AgentRequest) -> AgentRunResult:
    run = getattr(agent, "run", None)
    if not callable(run):
        return AgentRunResult.failure(
            f"Agent object {agent!r} does not provide run(request).",
            code="agent.invalid_adapter",
        )
    try:
        result = run(request)
    except Exception as exc:  # noqa: BLE001 - adapter failures become diagnostics.
        return AgentRunResult.failure(
            f"Agent adapter raised {type(exc).__name__}: {exc}",
            code="agent.exception",
            diagnostics=[
                Diagnostic.error(
                    "agent.exception",
                    str(exc) or type(exc).__name__,
                    source="agent",
                    details={"exception_type": type(exc).__name__},
                )
            ],
        )
    if isinstance(result, AgentRunResult):
        return result
    return AgentRunResult(output=str(result), ok=True)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip()).strip("._-")
    return slug or "phase"


def _path_text(path: PathInput) -> str:
    raw = os.fspath(path)
    if isinstance(raw, bytes):
        raise TypeError("task paths must be text, not bytes")
    if not raw:
        raise ValueError("task paths must not be empty")
    return raw


def _source_key(path: PathInput) -> str:
    raw = _path_text(path)
    source = Path(raw)
    if source.is_absolute():
        return str(source.resolve(strict=False))
    return str((Path.cwd() / source).resolve(strict=False))


def _stage_file(backend: LocalWorkspaceBackend, path: PathInput) -> str:
    raw = _path_text(path)
    source = Path(raw)
    if source.is_absolute():
        root = source.parent
        readable: PathInput = source.name
    else:
        root = Path.cwd()
        readable = raw
    staged = backend.stage(WorkspacePlan(root=root, readable=[readable]))
    return staged.staged_files[0]


def _workspace_name_for_revoke(path: PathInput, source_map: Mapping[str, str]) -> str:
    key = _source_key(path)
    if key in source_map:
        return source_map[key]
    raw = Path(_path_text(path))
    if raw.is_absolute():
        return raw.name
    return raw.as_posix()


def _workspace_snapshot(
    backend: LocalWorkspaceBackend,
    *,
    phase: Phase,
    staged_files: Sequence[str],
    revoked_files: Sequence[str],
) -> StagedWorkspace:
    plan = WorkspacePlan(
        root=Path.cwd(),
        workspace_root=backend.workspace_root,
        readable=backend.list_files(),
        revoked=revoked_files,
        metadata={"phase": phase.name},
    )
    return StagedWorkspace(
        workspace_root=backend.workspace_root,
        plan=plan,
        staged_files=tuple(staged_files),
        revoked_files=tuple(revoked_files),
        backend=backend,
    )


def _candidate_payload(candidate: Any) -> Any:
    if isinstance(candidate, str):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return candidate
    return candidate


@dataclass(frozen=True, slots=True, init=False)
class TaskId:
    """Stable task identifier."""

    value: str

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "value", _nonempty_text(value, field_name="task_id"))

    def __str__(self) -> str:
        return self.value

    def to_dict(self) -> dict[str, str]:
        return {"value": self.value}


@dataclass(frozen=True, slots=True, init=False)
class TaskVersionId:
    """Stable task-version identifier."""

    value: str

    def __init__(self, value: str = "v1") -> None:
        object.__setattr__(self, "value", _nonempty_text(value, field_name="version_id"))

    def __str__(self) -> str:
        return self.value

    def to_dict(self) -> dict[str, str]:
        return {"value": self.value}


def _coerce_task_id(value: TaskId | str | None, *, fallback: str) -> TaskId:
    if isinstance(value, TaskId):
        return value
    return TaskId(value if value is not None else fallback)


def _coerce_version_id(value: TaskVersionId | str | None) -> TaskVersionId:
    if isinstance(value, TaskVersionId):
        return value
    return TaskVersionId(value or "v1")


@dataclass(frozen=True, slots=True, init=False)
class TaskDefinition:
    """Serializable public definition for a task."""

    task_id: TaskId
    version_id: TaskVersionId
    name: str
    description: str | None
    phases: tuple[Phase, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        *,
        name: str,
        task_id: TaskId | str | None = None,
        version_id: TaskVersionId | str | None = None,
        description: str | None = None,
        phases: Sequence[Phase] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        task_name = _nonempty_text(name, field_name="name")
        if description is not None and not isinstance(description, str):
            raise TypeError("description must be a string or None")
        object.__setattr__(self, "name", task_name)
        object.__setattr__(self, "task_id", _coerce_task_id(task_id, fallback=task_name))
        object.__setattr__(self, "version_id", _coerce_version_id(version_id))
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "phases", tuple(phases or ()))
        object.__setattr__(self, "metadata", _metadata(metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": str(self.task_id),
            "version_id": str(self.version_id),
            "name": self.name,
            "description": self.description,
            "phases": [phase.to_dict() for phase in self.phases],
            "metadata": _json_ready(self.metadata),
        }


@dataclass(frozen=True, slots=True, init=False)
class Task:
    """Executable v1 task.

    Phase-based tasks run each phase in order against the same adapter. A
    multi-phase task requires adapter persistence so the second and later
    prompts can rely on provider-side session continuation.
    """

    definition: TaskDefinition
    agent: Any
    prompt: str | None
    validators: tuple[Any, ...]
    timeout_seconds: float | None
    provider_options: Mapping[str, Any]

    def __init__(
        self,
        *,
        name: str,
        agent: Any = None,
        phases: Sequence[Phase] | None = None,
        task_id: TaskId | str | None = None,
        version_id: TaskVersionId | str | None = None,
        description: str | None = None,
        prompt: str | None = None,
        validators: Sequence[Any] | None = None,
        timeout_seconds: float | None = None,
        provider_options: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if prompt is not None and not isinstance(prompt, str):
            raise TypeError("prompt must be a string or None")
        if timeout_seconds is not None:
            timeout_seconds = float(timeout_seconds)
            if timeout_seconds <= 0:
                raise ValueError("timeout_seconds must be positive")
        definition = TaskDefinition(
            name=name,
            task_id=task_id,
            version_id=version_id,
            description=description,
            phases=phases,
            metadata=metadata,
        )
        object.__setattr__(self, "definition", definition)
        object.__setattr__(self, "agent", agent)
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "validators", tuple(validators or ()))
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "provider_options", _metadata(provider_options))

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def task_id(self) -> TaskId:
        return self.definition.task_id

    @property
    def version_id(self) -> TaskVersionId:
        return self.definition.version_id

    @property
    def phases(self) -> tuple[Phase, ...]:
        return self.definition.phases

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.definition.to_dict(),
            "agent": _agent_name(self.agent) if self.agent is not None else None,
            "prompt": self.prompt,
            "validators": [type(validator).__name__ for validator in self.validators],
            "timeout_seconds": self.timeout_seconds,
            "provider_options": _json_ready(self.provider_options),
        }

    def run(self, *, artifact_root: Path | str | None = None) -> TaskResult:
        store = ArtifactStore(artifact_root) if artifact_root is not None else None
        observer = TaskObserver([JsonlSink(store.root)]) if store is not None else None
        state = _TaskRunState(task=self, artifact_store=store, observer=observer)
        state.emit(TaskEvent.workflow_started(workflow=self.name, task=str(self.task_id)))
        try:
            result = self._run(state)
            state.emit(
                TaskEvent.workflow_completed(
                    workflow=self.name,
                    task=str(self.task_id),
                    status="completed" if result.ok else "failed",
                    diagnostics=result.diagnostics,
                )
            )
            return state.finalize(result)
        finally:
            if observer is not None:
                observer.close()

    def _run(self, state: "_TaskRunState") -> TaskResult:
        if self.phases:
            return self._run_phases(state)
        if self.prompt is not None:
            return self._run_prompt_task(state)
        return TaskResult(
            ok=False,
            diagnostics=[
                Diagnostic.error(
                    "task.no_work",
                    "Task declares neither phases nor a prompt.",
                    source="task",
                )
            ],
        )

    def _missing_agent_result(self) -> TaskResult:
        return TaskResult(
            ok=False,
            diagnostics=[
                Diagnostic.error(
                    "task.agent_missing",
                    "Task requires an agent with run(request).",
                    source="task",
                )
            ],
        )

    def _run_prompt_task(self, state: "_TaskRunState") -> TaskResult:
        if self.agent is None or not callable(getattr(self.agent, "run", None)):
            return self._missing_agent_result()
        request = AgentRequest(
            prompt=self.prompt,
            timeout_seconds=self.timeout_seconds,
            provider_options=self.provider_options,
            metadata={"task": self.name, "task_id": str(self.task_id)},
        )
        agent_result = _run_agent(self.agent, request)
        agent_diagnostics = _coerce_diagnostics(
            agent_result.diagnostics,
            source="agent",
            default_code="agent.diagnostic",
        )
        report = build_validation_report(
            agent_result.output,
            self.validators,
            max_attempts=1,
            artifact_store=state.artifact_store,
            artifact_root=state.artifact_store.root if state.artifact_store is not None else None,
            workflow=self.name,
            task=str(self.task_id),
            stage=self.name,
            write_reports=state.artifact_store is not None,
            metadata={"execution": "agent", "agent_ok": agent_result.ok},
        )
        for event in report.events:
            state.emit(event)
        state.add_artifacts(report.artifacts, stage=self.name)
        ok = agent_result.ok and report.ok
        return TaskResult(
            ok=ok,
            output=report.output if ok else None,
            best_output=report.best_output if report.best_output is not None else agent_result.output,
            diagnostics=(*agent_diagnostics, *report.diagnostics),
            attempt_count=1,
            artifacts=report.artifacts,
        )

    def _run_phases(self, state: "_TaskRunState") -> TaskResult:
        if self.agent is None or not callable(getattr(self.agent, "run", None)):
            return self._missing_agent_result()

        capabilities = AgentCapabilities.from_any(getattr(self.agent, "capabilities", None))
        if len(self.phases) > 1 and not capabilities.supports_persistence:
            return TaskResult(
                ok=False,
                diagnostics=[
                    Diagnostic.error(
                        "task.persistence_unsupported",
                        "Task phases require a persistent agent session, but the adapter does not support persistence.",
                        source="task",
                        hint="Use an adapter with AgentCapabilities.supports_persistence=True.",
                        details={
                            "agent": _agent_name(self.agent),
                            "phase_count": len(self.phases),
                            "capabilities": capabilities.to_dict(),
                        },
                    )
                ],
            )

        backend = LocalWorkspaceBackend()
        source_map: dict[str, str] = {}
        revoked_names: set[str] = set()
        all_diagnostics: list[Diagnostic] = []
        best_output: Any = None
        final_output: Any = None
        attempt_count = 0

        for phase_index, phase in enumerate(self.phases):
            attempt_count = phase_index + 1
            state.emit(
                TaskEvent.stage_started(
                    stage=phase.name,
                    workflow=self.name,
                    task=str(self.task_id),
                    attempt=phase_index,
                )
            )
            state.emit(
                TaskEvent.attempt_started(
                    attempt=phase_index,
                    stage=phase.name,
                    workflow=self.name,
                    task=str(self.task_id),
                    details={"agent": _agent_name(self.agent)},
                )
            )

            try:
                staged_workspace = self._prepare_phase_workspace(
                    backend,
                    phase,
                    source_map=source_map,
                    revoked_names=revoked_names,
                )
            except Exception as exc:  # noqa: BLE001 - workspace failures are task diagnostics.
                diagnostic = Diagnostic.error(
                    "task.workspace_failed",
                    f"Preparing workspace for phase {phase.name!r} raised {type(exc).__name__}: {exc}",
                    source="task.workspace",
                    details={"phase": phase.name, "exception_type": type(exc).__name__},
                )
                all_diagnostics.append(diagnostic)
                state.emit(
                    TaskEvent.attempt_completed(
                        attempt=phase_index,
                        stage=phase.name,
                        workflow=self.name,
                        task=str(self.task_id),
                        status="failed",
                        diagnostics=[diagnostic],
                    )
                )
                state.emit(
                    TaskEvent.stage_completed(
                        stage=phase.name,
                        workflow=self.name,
                        task=str(self.task_id),
                        attempt=phase_index,
                        status="failed",
                        diagnostics=[diagnostic],
                    )
                )
                return TaskResult(
                    ok=False,
                    best_output=best_output,
                    diagnostics=tuple(all_diagnostics),
                    attempt_count=attempt_count,
                )

            self._record_phase_artifacts(
                state,
                phase=phase,
                phase_index=phase_index,
                workspace=staged_workspace,
            )
            request = AgentRequest(
                prompt=phase.prompt,
                workspace=staged_workspace,
                permissions={
                    "readable": staged_workspace.list_files(),
                    "revoked": list(staged_workspace.revoked_files),
                    "network": False,
                },
                timeout_seconds=self.timeout_seconds,
                provider_options=self.provider_options,
                metadata={
                    "task": self.name,
                    "task_id": str(self.task_id),
                    "phase": phase.name,
                    "phase_index": phase_index,
                    "persistent": len(self.phases) > 1,
                },
            )
            agent_result = _run_agent(self.agent, request)
            agent_diagnostics = _coerce_diagnostics(
                agent_result.diagnostics,
                source="agent",
                default_code="agent.diagnostic",
            )
            all_diagnostics.extend(agent_diagnostics)
            best_output = agent_result.output

            report = build_validation_report(
                agent_result.output,
                phase.validators,
                max_attempts=1,
                artifact_store=state.artifact_store,
                artifact_root=state.artifact_store.root if state.artifact_store is not None else None,
                workflow=self.name,
                task=str(self.task_id),
                stage=phase.name,
                write_reports=False,
                metadata={
                    "execution": "agent",
                    "agent_ok": agent_result.ok,
                    "phase": phase.name,
                    "phase_index": phase_index,
                    "workspace_files": staged_workspace.list_files(),
                    "revoked_files": list(staged_workspace.revoked_files),
                },
            )
            for event in report.events:
                state.emit(event)
            all_diagnostics.extend(report.diagnostics)
            best_output = report.best_output if report.best_output is not None else best_output
            self._write_validation_artifacts(state, phase=phase, phase_index=phase_index, report=report)

            accepted = bool(agent_result.ok and report.ok)
            state.emit(
                TaskEvent.attempt_completed(
                    attempt=phase_index,
                    stage=phase.name,
                    workflow=self.name,
                    task=str(self.task_id),
                    status="accepted" if accepted else "failed",
                    diagnostics=(*agent_diagnostics, *report.diagnostics),
                )
            )
            state.emit(
                TaskEvent.stage_completed(
                    stage=phase.name,
                    workflow=self.name,
                    task=str(self.task_id),
                    attempt=phase_index,
                    status="completed" if accepted else "failed",
                    diagnostics=(*agent_diagnostics, *report.diagnostics),
                    validation={"ok": accepted, "attempt_count": 1},
                )
            )

            if not accepted:
                return TaskResult(
                    ok=False,
                    best_output=best_output,
                    diagnostics=tuple(all_diagnostics),
                    attempt_count=attempt_count,
                )
            final_output = report.output
            best_output = final_output

        return TaskResult(
            ok=True,
            output=final_output,
            best_output=best_output,
            diagnostics=tuple(all_diagnostics),
            attempt_count=attempt_count,
        )

    def _prepare_phase_workspace(
        self,
        backend: LocalWorkspaceBackend,
        phase: Phase,
        *,
        source_map: dict[str, str],
        revoked_names: set[str],
    ) -> StagedWorkspace:
        staged_files: list[str] = []
        phase_revoked: list[str] = []
        for path in phase.revoke_files:
            name = _workspace_name_for_revoke(path, source_map)
            revoked_names.add(name)
            phase_revoked.append(name)

        for path in phase.workspace_files:
            key = _source_key(path)
            name = source_map.get(key)
            if name is not None and name in revoked_names:
                continue
            if name is None:
                staged_name = _stage_file(backend, path)
                source_map[key] = staged_name
            elif name not in revoked_names:
                staged_name = _stage_file(backend, path)
            else:
                continue
            staged_files.append(staged_name)

        if phase_revoked:
            backend.revoke(phase_revoked)
        return _workspace_snapshot(
            backend,
            phase=phase,
            staged_files=staged_files,
            revoked_files=phase_revoked,
        )

    def _record_phase_artifacts(
        self,
        state: "_TaskRunState",
        *,
        phase: Phase,
        phase_index: int,
        workspace: StagedWorkspace,
    ) -> None:
        if state.artifact_store is None:
            return
        prompt_artifact = state.artifact_store.write_text(
            f"phase_{phase_index}_{_slug(phase.name)}_prompt.md",
            phase.prompt if phase.prompt.endswith("\n") else f"{phase.prompt}\n",
            content_type="text/markdown",
        )
        state.add_artifact(prompt_artifact, stage=phase.name, attempt=phase_index)
        prompt_alias = state.artifact_store.write_text(
            f"prompt_{_slug(phase.name)}.md",
            phase.prompt if phase.prompt.endswith("\n") else f"{phase.prompt}\n",
            content_type="text/markdown",
        )
        state.add_artifact(prompt_alias, stage=phase.name, attempt=phase_index)

        workspace_artifact = state.artifact_store.write_json(
            f"phase_{phase_index}_{_slug(phase.name)}_workspace.json",
            workspace.to_dict(),
        )
        state.add_artifact(workspace_artifact, stage=phase.name, attempt=phase_index)

    def _write_validation_artifacts(
        self,
        state: "_TaskRunState",
        *,
        phase: Phase,
        phase_index: int,
        report: Any,
    ) -> None:
        if state.artifact_store is None:
            return
        artifact = state.artifact_store.write_json(
            f"phase_{phase_index}_{_slug(phase.name)}_validation_report.json",
            report.to_dict(),
        )
        state.add_artifact(artifact, stage=phase.name, attempt=phase_index)
        if phase_index == len(self.phases) - 1:
            final_artifact = state.artifact_store.write_json("validation_report.json", report.to_dict())
            state.add_artifact(final_artifact, stage=phase.name, attempt=phase_index)

class _TaskRunState:
    def __init__(
        self,
        *,
        task: Task,
        artifact_store: ArtifactStore | None,
        observer: TaskObserver | None,
    ) -> None:
        self.task = task
        self.artifact_store = artifact_store
        self.observer = observer
        self.events: list[TaskEvent] = []
        self.artifacts: list[ArtifactReference] = []

    def emit(self, event: TaskEvent) -> TaskEvent:
        self.events.append(event)
        if self.observer is not None:
            self.observer.emit(event)
        return event

    def add_artifact(
        self,
        artifact: ArtifactReference,
        *,
        stage: str | None = None,
        attempt: int | None = None,
    ) -> ArtifactReference:
        self.artifacts.append(artifact)
        self.emit(
            TaskEvent.artifact_recorded(
                artifact=_artifact_to_dict(artifact),
                workflow=self.task.name,
                task=str(self.task.task_id),
                stage=stage,
                attempt=attempt,
            )
        )
        return artifact

    def add_artifacts(
        self,
        artifacts: Sequence[ArtifactReference],
        *,
        stage: str | None = None,
        attempt: int | None = None,
    ) -> None:
        for artifact in artifacts:
            self.add_artifact(artifact, stage=stage, attempt=attempt)

    def finalize(self, result: TaskResult) -> TaskResult:
        artifacts = [*self.artifacts, *result.artifacts]
        if self.artifact_store is not None:
            events_path = self.artifact_store.root / "events.jsonl"
            if events_path.exists():
                artifacts.append(
                    self.artifact_store.record(
                        "events.jsonl",
                        content_type="application/x-ndjson",
                    )
                )
        finalized = TaskResult(
            ok=result.ok,
            output=result.output,
            best_output=result.best_output,
            diagnostics=result.diagnostics,
            attempt_count=result.attempt_count,
            events=tuple(self.events),
            artifacts=_dedupe_artifacts(artifacts),
        )
        if self.artifact_store is None:
            return finalized
        task_result_artifact = self.artifact_store.write_json("task_result.json", finalized.to_dict())
        return TaskResult(
            ok=finalized.ok,
            output=finalized.output,
            best_output=finalized.best_output,
            diagnostics=finalized.diagnostics,
            attempt_count=finalized.attempt_count,
            events=finalized.events,
            artifacts=_dedupe_artifacts((*finalized.artifacts, task_result_artifact)),
        )


def _dedupe_artifacts(artifacts: Sequence[ArtifactReference]) -> tuple[ArtifactReference, ...]:
    deduped: list[ArtifactReference] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for artifact in artifacts:
        data = _artifact_to_dict(artifact)
        key = (data.get("name"), data.get("path"), data.get("sha256"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return tuple(deduped)


__all__ = ["Task", "TaskDefinition", "TaskId", "TaskVersionId"]
