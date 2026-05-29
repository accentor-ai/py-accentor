from __future__ import annotations

import json

from accentor.configure import (
    PermissionCompiler,
    PermissionIntent,
    WorkspaceIntent,
    compile_permissions,
    compile_workspace,
    compile_workspace_with_diagnostics,
)


def assert_json_stable(payload: dict) -> dict:
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    return json.loads(encoded)


def test_permission_intent_compiles_to_provider_neutral_permission_set(tmp_path) -> None:
    source = tmp_path / "inputs" / "source.txt"
    editable = tmp_path / "src" / "worker.py"
    source.parent.mkdir()
    editable.parent.mkdir()
    source.write_text("source", encoding="utf-8")
    editable.write_text("print('old')\n", encoding="utf-8")

    result = PermissionIntent(
        root=tmp_path,
        readable=[source],
        editable=[editable],
        network={"search": True},
        metadata={"stage": "repair"},
    ).compile_with_diagnostics()
    permissions = result.permissions

    assert result.diagnostics == ()
    assert permissions.readable == ("inputs/source.txt",)
    assert permissions.editable == ("src/worker.py",)
    assert permissions.network.enabled is True
    assert permissions.network.search is True
    assert permissions.commands.enabled is False
    assert_json_stable(result.to_dict())


def test_explicit_permission_shorthands_keep_readable_and_editable_distinct(tmp_path) -> None:
    readable = tmp_path / "inputs" / "guide.txt"
    editable = tmp_path / "src" / "app.py"
    readable.parent.mkdir()
    editable.parent.mkdir()
    readable.write_text("read", encoding="utf-8")
    editable.write_text("old", encoding="utf-8")

    permissions = PermissionCompiler(root=tmp_path).compile(
        readable=[readable],
        editable=[editable],
        network=False,
    )

    assert permissions.readable == ("inputs/guide.txt",)
    assert permissions.editable == ("src/app.py",)
    assert permissions.network.enabled is False
    assert "src/app.py" not in permissions.readable


def test_empty_prompt_only_scope_grants_no_files_writes_or_network(tmp_path) -> None:
    permissions = PermissionIntent(root=tmp_path).compile()
    workspace = WorkspaceIntent(root=tmp_path).compile()

    assert permissions.readable == ()
    assert permissions.editable == ()
    assert permissions.network.enabled is False
    assert workspace.readable == ()
    assert workspace.editable == ()
    assert workspace.revoked == ()
    assert workspace.staged_paths == ()


def test_omitted_network_policy_defaults_to_no_extra_network_grant(tmp_path) -> None:
    default_permissions = compile_permissions(root=tmp_path)
    explicit_false_permissions = compile_permissions(root=tmp_path, network=False)
    search_permissions = compile_permissions(root=tmp_path, search=True)

    assert default_permissions.network.enabled is False
    assert default_permissions.network.search is False
    assert explicit_false_permissions.network.enabled is False
    assert search_permissions.network.enabled is True
    assert search_permissions.network.search is True


def test_workspace_intent_shorthands_and_revocation_plan(tmp_path) -> None:
    guidelines = tmp_path / "inputs" / "task_guidelines.txt"
    challenge = tmp_path / "inputs" / "challenge.json"
    guidelines.parent.mkdir()
    guidelines.write_text("guidelines", encoding="utf-8")
    challenge.write_text("{}", encoding="utf-8")

    plan = compile_workspace(
        root=tmp_path,
        workspace_files=[guidelines, challenge],
        revoke_files=[guidelines],
        outputs=["outputs/answer.json"],
    )

    assert plan.readable == ("inputs/task_guidelines.txt", "inputs/challenge.json")
    assert plan.revoked == ("inputs/task_guidelines.txt",)
    assert plan.staged_paths == ("inputs/challenge.json",)
    assert plan.exportable == ("outputs/answer.json",)


def test_permission_revoke_files_compiles_to_revoke_revision(tmp_path) -> None:
    guidelines = tmp_path / "inputs" / "task_guidelines.txt"
    challenge = tmp_path / "inputs" / "challenge.json"
    guidelines.parent.mkdir()
    guidelines.write_text("guidelines", encoding="utf-8")
    challenge.write_text("{}", encoding="utf-8")

    permissions = compile_permissions(
        root=tmp_path,
        readable=[guidelines, challenge],
        revoke_files=[guidelines],
    )

    assert permissions.readable == ("inputs/challenge.json",)
    assert [revision.action for revision in permissions.revisions] == ["revoke_read"]
    assert permissions.revisions[0].paths == ("inputs/task_guidelines.txt",)


def test_workspace_globs_expand_to_sorted_file_paths(tmp_path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "b.txt").write_text("b", encoding="utf-8")
    (inputs / "a.txt").write_text("a", encoding="utf-8")
    (inputs / "skip.md").write_text("skip", encoding="utf-8")

    result = compile_workspace_with_diagnostics(root=tmp_path, workspace_files=["inputs/*.txt"])

    assert result.diagnostics == ()
    assert result.plan.readable == ("inputs/a.txt", "inputs/b.txt")


def test_permission_compiler_reports_underspecified_repair_scope() -> None:
    result = PermissionIntent(repair=True).compile_with_diagnostics()
    codes = {diagnostic.code for diagnostic in result.diagnostics}

    assert "configure.permissions.repair_editable_missing" in codes
    assert "configure.permissions.repair_scope_missing" in codes
