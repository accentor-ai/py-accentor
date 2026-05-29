from __future__ import annotations

import hashlib

import pytest

from accentor.record.artifacts import (
    ArtifactPathError,
    ArtifactStore,
    promote_artifact,
    promote_patch,
    promote_validation_report,
)


def test_artifact_store_writes_nested_paths_and_reads_json(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")

    record = store.write_json("nested/task_result.json", {"ok": True, "value": 3})

    assert record.name == "nested/task_result.json"
    assert record.size_bytes > 0
    assert store.read_json("nested/task_result.json") == {"ok": True, "value": 3}
    assert (store.root / "nested" / "task_result.json").is_file()


def test_artifact_store_manifest_contains_hashes_and_stable_data(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    store.write_text("events.jsonl", '{"event":"start"}\n')
    store.write_bytes("reports/blob.bin", b"abc")

    manifest = store.manifest()
    by_name = {item["name"]: item for item in manifest["artifacts"]}

    assert manifest["artifact_root"] == str(store.root)
    assert manifest["artifact_count"] == 2
    assert by_name["events.jsonl"]["sha256"] == hashlib.sha256(b'{"event":"start"}\n').hexdigest()
    assert by_name["events.jsonl"]["size_bytes"] == len(b'{"event":"start"}\n')
    assert by_name["reports/blob.bin"]["sha256"] == hashlib.sha256(b"abc").hexdigest()


@pytest.mark.parametrize(
    "artifact_name",
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
def test_artifact_store_rejects_unsafe_artifact_names(tmp_path, artifact_name):
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactPathError):
        store.write_text(artifact_name, "unsafe")


def test_artifact_store_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    store = ArtifactStore(root)

    with pytest.raises(ArtifactPathError):
        store.write_text("linked/escape.txt", "unsafe")


def test_promote_helpers_copy_files_and_write_standard_reports(tmp_path):
    generated = tmp_path / "generated.txt"
    generated.write_text("generated output", encoding="utf-8")
    store = ArtifactStore(tmp_path / "artifacts")

    copied = promote_artifact(store, generated, "generated/output.txt")
    patch = promote_patch(store, "diff --git a/file b/file\n")
    report = promote_validation_report(store, {"ok": True})

    assert copied.name == "generated/output.txt"
    assert store.read_text("generated/output.txt") == "generated output"
    assert patch.name == "proposed_diff.patch"
    assert report.name == "validation_report.json"
    assert store.read_json("validation_report.json") == {"ok": True}
