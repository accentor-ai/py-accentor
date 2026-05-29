from __future__ import annotations

"""Public Accentor v1 surface."""

from accentor.configure import DispatchPlan, PermissionIntent, WorkspaceIntent
from accentor.core.decorators import (
    StageConfigurationError,
    StageValidationError,
    WorkflowError,
    stage,
    workflow,
)
from accentor.core.task import Task, TaskResult, TaskResultError
from accentor.evaluate.validation import ValidationResult, Validator

__version__ = "3.0.0a1"

__all__ = [
    "PermissionIntent",
    "DispatchPlan",
    "StageConfigurationError",
    "StageValidationError",
    "Task",
    "TaskResult",
    "TaskResultError",
    "ValidationResult",
    "Validator",
    "WorkflowError",
    "WorkspaceIntent",
    "__version__",
    "stage",
    "workflow",
]
