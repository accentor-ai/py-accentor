from __future__ import annotations

"""Configuration-layer intent records and compilers."""

from accentor.configure.context import ConfigureContext, ContextSelector
from accentor.configure.dispatch_plan import DispatchPlan, SandboxMode
from accentor.configure.permissions import (
    PermissionCompilation,
    PermissionCompiler,
    PermissionIntent,
    compile_permissions,
    compile_permissions_with_diagnostics,
)
from accentor.configure.prompt import (
    CompiledPrompt,
    PromptCompiler,
    PromptSection,
    build_prompt_sections,
    build_success_criteria_text,
)
from accentor.configure.workspace import (
    WorkspaceCompilation,
    WorkspaceCompiler,
    WorkspaceIntent,
    compile_workspace,
    compile_workspace_with_diagnostics,
)

__all__ = [
    "ConfigureContext",
    "ContextSelector",
    "DispatchPlan",
    "PermissionCompilation",
    "PermissionCompiler",
    "PermissionIntent",
    "CompiledPrompt",
    "PromptCompiler",
    "PromptSection",
    "SandboxMode",
    "WorkspaceCompilation",
    "WorkspaceCompiler",
    "WorkspaceIntent",
    "build_prompt_sections",
    "build_success_criteria_text",
    "compile_permissions",
    "compile_permissions_with_diagnostics",
    "compile_workspace",
    "compile_workspace_with_diagnostics",
]
