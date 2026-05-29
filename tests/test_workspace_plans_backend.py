from __future__ import annotations

import json

import pytest

from accentor.dispatch.workspace import (
    LocalWorkspaceBackend,
    WorkspaceExportError,
    WorkspacePathError,
    WorkspacePlan,
)


def test_workspace_plan_records_paths_and_metadata(tmp_path):
    source = tmp_path / "inputs" / "notes.txt"
    editable = tmp_path / "drafts" / "reply.txt"
    source.parent.mkdir()
    editable.parent.mkdir()
    source.write_text("notes", encoding="utf-8")
    editable.write_text("draft", encoding="utf-8")

    plan = WorkspacePlan(
        root=tmp_path,
        readable=[source],
        editable=["drafts/reply.txt"],
        revoke_files=["inputs/notes.txt"],
        outputs=["outputs/result.json"],
        metadata={"stage": "draft_reply"},
    )

    payload = json.loads(json.dumps(plan.to_dict(), sort_keys=True))

    assert plan.readable == ("inputs/notes.txt",)
    assert plan.editable == ("drafts/reply.txt",)
    assert plan.revoked == ("inputs/notes.txt",)
    assert plan.exportable == ("outputs/result.json",)
    assert plan.staged_paths == ("drafts/reply.txt",)
    assert payload["metadata"] == {"stage": "draft_reply"}


def test_backend_stages_readable_and_editable_files(tmp_path):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "inputs" / "guide.txt").write_text("read me", encoding="utf-8")
    (tmp_path / "src" / "worker.py").write_text("print('old')\n", encoding="utf-8")

    plan = WorkspacePlan(
        root=tmp_path,
        readable=["inputs/guide.txt"],
        editable=["src/worker.py"],
    )
    backend = LocalWorkspaceBackend(tmp_path / "stage")

    staged = backend.stage(plan)

    assert staged.read_text("inputs/guide.txt") == "read me"
    assert staged.read_text("src/worker.py") == "print('old')\n"
    assert staged.list_files() == ["inputs/guide.txt", "src/worker.py"]
    assert staged.plan.workspace_root == backend.workspace_root


def test_revoked_files_are_absent_from_staged_workspace(tmp_path):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "guidelines.txt").write_text("secret line", encoding="utf-8")
    (tmp_path / "inputs" / "challenge.json").write_text("{}", encoding="utf-8")
    plan = WorkspacePlan(
        root=tmp_path,
        readable=["inputs/guidelines.txt", "inputs/challenge.json"],
        revoke_files=["inputs/guidelines.txt"],
    )
    backend = LocalWorkspaceBackend(tmp_path / "stage")

    staged = backend.prepare(plan)

    assert "inputs/guidelines.txt" not in staged.list_virtual_files()
    assert staged.read_virtual_file("inputs/challenge.json") == "{}"
    assert not (backend.workspace_root / "inputs" / "guidelines.txt").exists()


def test_virtual_read_write_helpers_use_real_isolated_files(tmp_path):
    backend = LocalWorkspaceBackend(tmp_path / "stage")

    record = backend.write_virtual_file("nested/result.txt", "ready")

    assert record.name == "nested/result.txt"
    assert backend.read_virtual_file("nested/result.txt") == "ready"
    assert (tmp_path / "stage" / "nested" / "result.txt").is_file()
    assert backend.list_virtual_files() == ["nested/result.txt"]


def test_export_copies_only_declared_outputs(tmp_path):
    plan = WorkspacePlan(root=tmp_path, outputs=["outputs/result.json"])
    backend = LocalWorkspaceBackend(tmp_path / "stage")
    backend.write_text("outputs/result.json", '{"ok": true}\n')
    backend.write_text("outputs/private.txt", "do not export")

    records = backend.export(plan, tmp_path / "exported")

    assert [record.name for record in records] == ["outputs/result.json"]
    assert (tmp_path / "exported" / "outputs" / "result.json").read_text(encoding="utf-8") == (
        '{"ok": true}\n'
    )
    assert not (tmp_path / "exported" / "outputs" / "private.txt").exists()


def test_exporting_undeclared_file_fails_with_diagnostic(tmp_path):
    plan = WorkspacePlan(root=tmp_path, outputs=["outputs/result.json"])
    backend = LocalWorkspaceBackend(tmp_path / "stage")
    backend.write_text("outputs/private.txt", "do not export")

    with pytest.raises(WorkspaceExportError) as exc_info:
        backend.export(plan, tmp_path / "exported", paths=["outputs/private.txt"])

    diagnostic = exc_info.value.diagnostic()
    assert diagnostic["code"] == "workspace.export_undeclared"
    assert diagnostic["details"]["path"] == "outputs/private.txt"


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../escape.txt",
        "nested/../../escape.txt",
        "/tmp/escape.txt",
        "",
        ".",
        r"C:\tmp\escape.txt",
        r"nested\escape.txt",
    ],
)
def test_workspace_rejects_traversal_and_absolute_paths(tmp_path, unsafe_path):
    with pytest.raises(WorkspacePathError):
        WorkspacePlan(root=tmp_path, readable=[unsafe_path])


def test_workspace_rejects_symlink_escape_on_seed(tmp_path):
    outside = tmp_path / "outside"
    root = tmp_path / "root"
    outside.mkdir()
    root.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    linked = root / "linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available on this filesystem")

    with pytest.raises(WorkspacePathError):
        WorkspacePlan(root=root, readable=["linked/secret.txt"])


def test_workspace_rejects_symlink_escape_on_virtual_write(tmp_path):
    outside = tmp_path / "outside"
    stage = tmp_path / "stage"
    outside.mkdir()
    stage.mkdir()
    (stage / "linked").symlink_to(outside, target_is_directory=True)
    backend = LocalWorkspaceBackend(stage)

    with pytest.raises(WorkspacePathError):
        backend.write_virtual_file("linked/escape.txt", "unsafe")

    with pytest.raises(WorkspacePathError):
        backend.write_virtual_file("linked/nested/escape.txt", "unsafe")
    assert not (outside / "nested").exists()
