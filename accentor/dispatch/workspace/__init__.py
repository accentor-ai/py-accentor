from __future__ import annotations

"""Workspace planning, local staging, and diff helpers."""

from accentor.dispatch.workspace.backends import (
    LocalStagingBackend,
    LocalWorkspaceBackend,
    StagedWorkspace,
    WorkspaceExportError,
    WorkspaceExportRecord,
    WorkspaceFileRecord,
)
from accentor.dispatch.workspace.diff import (
    DiffScopeError,
    DiffScopeReport,
    DiffScopeVerdict,
    FileChange,
    build_patch_text,
    diff_workspaces,
    evaluate_diff_scope,
    write_diff_scope_artifacts,
)
from accentor.dispatch.workspace.plans import WorkspaceError, WorkspacePathError, WorkspacePlan

__all__ = [
    "DiffScopeError",
    "DiffScopeReport",
    "DiffScopeVerdict",
    "FileChange",
    "LocalStagingBackend",
    "LocalWorkspaceBackend",
    "StagedWorkspace",
    "WorkspaceError",
    "WorkspaceExportError",
    "WorkspaceExportRecord",
    "WorkspaceFileRecord",
    "WorkspacePathError",
    "WorkspacePlan",
    "build_patch_text",
    "diff_workspaces",
    "evaluate_diff_scope",
    "write_diff_scope_artifacts",
]
