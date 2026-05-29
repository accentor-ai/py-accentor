"""Provider-neutral dispatch policy records and helpers."""

from __future__ import annotations

from accentor.dispatch.policy.commands import CommandPolicy
from accentor.dispatch.policy.environment import EnvironmentPolicy, PRESENT_ENV_VALUE, REDACTED_ENV_VALUE
from accentor.dispatch.policy.network import NetworkPolicy
from accentor.dispatch.policy.permissions import PermissionSet, PolicyDecision
from accentor.dispatch.policy.revisions import GrantRead, PermissionRevision, RevokeRead

from .paths import (
    NormalizedPath,
    PathPolicy,
    PathPolicyBatchDecision,
    PathPolicyDecision,
    PathPolicyError,
    check_path,
    check_paths,
    is_path_allowed,
    normalize_path,
    normalize_policy_pattern,
    normalize_under_root,
    path_matches_pattern,
)

__all__ = [
    "CommandPolicy",
    "EnvironmentPolicy",
    "GrantRead",
    "NetworkPolicy",
    "NormalizedPath",
    "PermissionRevision",
    "PermissionSet",
    "PathPolicy",
    "PathPolicyBatchDecision",
    "PathPolicyDecision",
    "PathPolicyError",
    "PolicyDecision",
    "PRESENT_ENV_VALUE",
    "REDACTED_ENV_VALUE",
    "RevokeRead",
    "check_path",
    "check_paths",
    "is_path_allowed",
    "normalize_path",
    "normalize_policy_pattern",
    "normalize_under_root",
    "path_matches_pattern",
]
