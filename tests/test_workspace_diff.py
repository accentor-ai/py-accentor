from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from accentor.dispatch.workspace.diff import (
    DiffScopeError,
    build_patch_text,
    diff_workspaces,
    evaluate_diff_scope,
    write_diff_scope_artifacts,
)
from accentor.record.artifacts import ArtifactStore


def assert_json_stable(payload: Any) -> Any:
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    decoded = json.loads(encoded)
    assert json.dumps(decoded, allow_nan=False, sort_keys=True) == encoded
    return decoded


def write_file(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_changed_file_inside_editable_scope_passes(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    write_file(before, "src/app.py", "value = 1\n")
    editable_file = write_file(after, "src/app.py", "value = 2\n")

    report = diff_workspaces(before, after, editable=[editable_file])
    verdict = report.verdict

    assert verdict.ok
    assert verdict.changed_paths == ("src/app.py",)
    assert verdict.modified_paths == ("src/app.py",)
    assert verdict.violating_paths == ()
    assert verdict.changes[0].inside_editable_scope is True
    assert assert_json_stable(verdict.to_dict())["ok"] is True


def test_change_outside_editable_scope_is_reported_as_violation(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    write_file(before, "src/app.py", "value = 1\n")
    write_file(after, "src/app.py", "value = 2\n")
    write_file(before, "README.md", "old\n")
    write_file(after, "README.md", "new\n")

    verdict = evaluate_diff_scope(before, after, editable=["src/app.py"])

    assert not verdict.ok
    assert verdict.changed_paths == ("README.md", "src/app.py")
    assert verdict.violating_paths == ("README.md",)
    by_path = {change.path: change for change in verdict.changes}
    assert by_path["src/app.py"].inside_editable_scope is True
    assert by_path["README.md"].inside_editable_scope is False


def test_added_file_inside_editable_directory_passes(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "generated").mkdir()
    write_file(after, "generated/new.txt", "new\n")

    verdict = evaluate_diff_scope(before, after, editable=["generated"])

    assert verdict.ok
    assert verdict.added_paths == ("generated/new.txt",)
    assert verdict.violating_paths == ()


def test_deleted_file_is_detected_and_scoped(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    write_file(before, "generated/obsolete.txt", "remove me\n")

    verdict = evaluate_diff_scope(before, after, editable=["generated"])

    assert verdict.ok
    assert verdict.changed_paths == ("generated/obsolete.txt",)
    assert verdict.deleted_paths == ("generated/obsolete.txt",)
    assert verdict.changes[0].status == "deleted"
    assert verdict.changes[0].before_size_bytes == len("remove me\n")
    assert verdict.changes[0].after_size_bytes is None


def test_deleted_file_outside_editable_scope_is_violation(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    write_file(before, "protected.txt", "do not remove\n")

    verdict = evaluate_diff_scope(before, after, editable=[])

    assert not verdict.ok
    assert verdict.deleted_paths == ("protected.txt",)
    assert verdict.violating_paths == ("protected.txt",)


def test_best_effort_patch_text_for_simple_edit(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    write_file(before, "src/app.py", "value = 1\n")
    write_file(after, "src/app.py", "value = 2\n")

    report = diff_workspaces(before, after, editable=["src"])

    assert report.verdict.patch_available is True
    assert "--- a/src/app.py" in report.patch_text
    assert "+++ b/src/app.py" in report.patch_text
    assert "-value = 1" in report.patch_text
    assert "+value = 2" in report.patch_text
    assert build_patch_text(before, after) == report.patch_text


def test_write_diff_scope_artifacts(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    write_file(before, "src/app.py", "value = 1\n")
    write_file(after, "src/app.py", "value = 2\n")
    store = ArtifactStore(tmp_path / "artifacts")

    report = write_diff_scope_artifacts(store, before, after, editable=["src/app.py"])

    assert report.verdict.ok
    assert store.read_json("diff_scope_verdict.json") == report.verdict.to_dict()
    assert store.read_text("proposed_diff.patch") == report.patch_text


def test_editable_paths_reject_workspace_escape(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    outside = tmp_path / "outside.txt"
    before.mkdir()
    after.mkdir()
    outside.write_text("outside", encoding="utf-8")

    try:
        evaluate_diff_scope(before, after, editable=[outside])
    except DiffScopeError as exc:
        assert "outside the compared workspace roots" in str(exc)
    else:
        raise AssertionError("expected DiffScopeError")


def test_workspace_package_exports_diff_scope_helpers() -> None:
    import accentor.dispatch.workspace as workspace

    assert workspace.evaluate_diff_scope is evaluate_diff_scope
    assert workspace.diff_workspaces is diff_workspaces
