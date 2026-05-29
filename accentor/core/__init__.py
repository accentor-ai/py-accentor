from __future__ import annotations

"""Core Accentor execution records, decorators, and composition helpers."""

_EXPORT_MODULES = {
    "Diagnostic": "accentor.core.task",
    "Phase": "accentor.core.steps",
    "StageConfigurationError": "accentor.core.decorators",
    "StageValidationError": "accentor.core.decorators",
    "Step": "accentor.core.steps",
    "StepContext": "accentor.core.steps",
    "StepKind": "accentor.core.steps",
    "StepResult": "accentor.core.steps",
    "Task": "accentor.core.task",
    "TaskAttempt": "accentor.core.task",
    "TaskDefinition": "accentor.core.task",
    "TaskEvent": "accentor.core.task",
    "TaskId": "accentor.core.task",
    "TaskResult": "accentor.core.task",
    "TaskResultError": "accentor.core.task",
    "TaskRun": "accentor.core.task",
    "TaskVersionId": "accentor.core.task",
    "WorkflowError": "accentor.core.decorators",
    "retry": "accentor.core.composition",
    "sequence": "accentor.core.composition",
    "stage": "accentor.core.decorators",
    "workflow": "accentor.core.decorators",
}


def __getattr__(name: str) -> object:
    if name not in _EXPORT_MODULES:
        raise AttributeError(name)
    from importlib import import_module

    module = import_module(_EXPORT_MODULES[name])
    value = getattr(module, name)
    globals()[name] = value
    return value

__all__ = [
    "Diagnostic",
    "Phase",
    "StageConfigurationError",
    "StageValidationError",
    "Step",
    "StepContext",
    "StepKind",
    "StepResult",
    "Task",
    "TaskAttempt",
    "TaskDefinition",
    "TaskEvent",
    "TaskId",
    "TaskResult",
    "TaskResultError",
    "TaskRun",
    "TaskVersionId",
    "WorkflowError",
    "retry",
    "sequence",
    "stage",
    "workflow",
]
