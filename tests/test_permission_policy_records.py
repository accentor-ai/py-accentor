from __future__ import annotations

import json

from accentor.dispatch.agents.base import AgentCapabilities
from accentor.dispatch.policy import (
    CommandPolicy,
    EnvironmentPolicy,
    GrantRead,
    NetworkPolicy,
    PermissionSet,
    RevokeRead,
)


def assert_json_stable(payload: dict) -> dict:
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    return json.loads(encoded)


def test_permission_set_construction_is_json_stable() -> None:
    permissions = PermissionSet(
        readable=["inputs/guidelines.txt", "inputs/guidelines.txt"],
        editable=["outputs/answer.json"],
        network={"enabled": True, "search": True},
        commands=False,
        environment={"inherit": False, "allow": ["PATH"], "redact": ["API_TOKEN"]},
        metadata={"stage": "draft"},
    )

    assert permissions.readable == ("inputs/guidelines.txt",)
    assert permissions.editable == ("outputs/answer.json",)
    assert permissions.network.enabled is True
    assert permissions.network.search is True

    payload = assert_json_stable(permissions.to_dict())
    assert payload["readable"] == ["inputs/guidelines.txt"]
    assert payload["editable"] == ["outputs/answer.json"]
    assert payload["network"]["search"] is True
    assert payload["environment"]["redacted_variables"] == ["API_TOKEN"]


def test_provider_sandbox_mapping_and_search_flag_records() -> None:
    permissions = PermissionSet(
        readable=["inputs/source.txt"],
        editable=["outputs/result.txt"],
        network=NetworkPolicy(search=True),
    )

    decision = permissions.evaluate(
        provider="codex",
        capabilities=AgentCapabilities(files=True, sandbox=True, shell=True),
    )
    payload = assert_json_stable(decision.to_dict())

    assert decision.ok is True
    assert payload["sandbox_mode"] == "workspace-write"
    assert payload["provider_flags"]["sandbox"] == "workspace-write"
    assert payload["provider_flags"]["search"] is True
    assert payload["post_run_checks"] == ["staged_read_scope", "diff_scope", "export_scope"]
    assert "provider_options" not in payload


def test_unsupported_network_and_command_policies_return_structured_diagnostics() -> None:
    permissions = PermissionSet(
        network=NetworkPolicy(enabled=True, allowed_hosts=["api.example.test"]),
        commands=CommandPolicy(allowed_commands=["python"]),
    )

    decision = permissions.evaluate("codex", capabilities=AgentCapabilities(shell=True))
    payload = assert_json_stable(decision.to_dict())
    codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}

    assert decision.ok is False
    assert "policy.network.host_allowlist_unsupported" in codes
    assert "policy.commands.allowlist_unsupported" in codes
    assert "policy.network.host_allowlist_unsupported" in payload["unsupported"]


def test_environment_redaction_record_contains_no_raw_values() -> None:
    policy = EnvironmentPolicy(
        inherit=False,
        allow=["PATH", "API_TOKEN"],
        deny=["HOME"],
        redact=["API_TOKEN"],
    )

    record = policy.redaction_record(
        {
            "PATH": "/usr/bin",
            "API_TOKEN": "secret-token",
            "HOME": "/Users/alice",
        }
    )
    encoded = json.dumps(record, sort_keys=True)

    assert record["variables"]["API_TOKEN"] == "[REDACTED]"
    assert record["variables"]["PATH"] == "[PRESENT]"
    assert "HOME" not in record["variables"]
    assert "secret-token" not in encoded
    assert "/Users/alice" not in encoded

    decision = PermissionSet(environment=policy).evaluate("codex")
    assert decision.ok is False
    assert decision.diagnostics[0].code == "policy.environment.enforcement_unsupported"


def test_grant_and_revoke_read_revision_records_apply_to_permission_set() -> None:
    permissions = PermissionSet(readable=["inputs/guidelines.txt"])
    grant = GrantRead(["inputs/challenge.txt"], phase="verification", reason="read challenge")
    revoke = RevokeRead(["inputs/guidelines.txt"], phase="verification", reason="revoke source")

    granted = grant.apply(permissions)
    revoked = revoke.apply(granted)
    payload = assert_json_stable(revoked.to_dict())

    assert granted.readable == ("inputs/guidelines.txt", "inputs/challenge.txt")
    assert revoked.readable == ("inputs/challenge.txt",)
    assert [revision["action"] for revision in payload["revisions"]] == ["grant_read", "revoke_read"]
    assert payload["revisions"][0]["phase"] == "verification"
