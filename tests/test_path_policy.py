from __future__ import annotations

import unicodedata

import pytest

from accentor.dispatch.policy.paths import (
    MAX_PATH_SEGMENT_LENGTH,
    PathPolicy,
    PathPolicyError,
    normalize_under_root,
    path_matches_pattern,
)


def test_normalize_under_root_reports_relative_paths_for_relative_and_absolute_inputs(tmp_path):
    root = tmp_path / "workspace"
    target = root / "nested" / "allowed.txt"
    target.parent.mkdir(parents=True)
    target.write_text("ok", encoding="utf-8")

    relative = normalize_under_root(root, "nested/allowed.txt", must_exist=True)
    absolute = normalize_under_root(root, target, allow_absolute=True, must_exist=True)

    assert relative.root == root.resolve()
    assert relative.path == target.resolve()
    assert relative.relative_path == "nested/allowed.txt"
    assert relative.requested_relative_path == "nested/allowed.txt"
    assert absolute.relative_path == "nested/allowed.txt"
    assert absolute.to_dict()["relative_path"] == "nested/allowed.txt"


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../escape.txt",
        "nested/../../escape.txt",
        "",
        ".",
        "./nested/allowed.txt",
        "nested/./allowed.txt",
        "nested//allowed.txt",
        "nested/allowed.txt/",
        "/tmp/escape.txt",
        "C:/tmp/escape.txt",
        r"C:\tmp\escape.txt",
        r"nested\allowed.txt",
        "bad\x00name.txt",
        "bad\nname.txt",
        "bad\rname.txt",
        f"{'a' * (MAX_PATH_SEGMENT_LENGTH + 1)}.txt",
        unicodedata.normalize("NFD", "caf\u00e9.txt"),
    ],
)
def test_strict_normalization_rejects_ambiguous_or_escaping_paths(tmp_path, unsafe_path):
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(PathPolicyError):
        normalize_under_root(root, unsafe_path)


def test_absolute_paths_must_be_explicitly_allowed_and_still_stay_inside_root(tmp_path):
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    target = root / "allowed.txt"
    root.mkdir()
    outside.mkdir()
    target.write_text("ok", encoding="utf-8")
    outside_target = outside / "escape.txt"
    outside_target.write_text("no", encoding="utf-8")

    with pytest.raises(PathPolicyError):
        normalize_under_root(root, target)

    assert normalize_under_root(root, target, allow_absolute=True).relative_path == "allowed.txt"
    with pytest.raises(PathPolicyError):
        normalize_under_root(root, outside_target, allow_absolute=True)


def test_denied_paths_win_over_matching_allow_patterns(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    policy = PathPolicy(
        root,
        allowed=["**", "secrets/**"],
        denied=["secrets/**"],
    )

    decision = policy.check("secrets/public.txt")

    assert not decision.allowed
    assert decision.reason == "denied"
    assert decision.matched_deny == "secrets/**"
    assert decision.relative_path == "secrets/public.txt"


def test_symlink_escape_and_symlink_chains_are_rejected(tmp_path):
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "escape.txt").write_text("outside", encoding="utf-8")
    linked = root / "linked_outside"
    chain = root / "chain"
    try:
        linked.symlink_to(outside, target_is_directory=True)
        chain.symlink_to(linked, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    policy = PathPolicy(root, allowed=["**"])

    direct = policy.check("linked_outside/escape.txt")
    chained = policy.check("chain/escape.txt")

    assert not direct.allowed
    assert "escapes root" in (direct.error or "")
    assert not chained.allowed
    assert "escapes root" in (chained.error or "")
    with pytest.raises(PathPolicyError):
        normalize_under_root(root, "linked_outside/escape.txt")


def test_file_and_glob_matching_is_path_segment_aware(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    policy = PathPolicy(
        root,
        allowed=["reports/*.txt", "src/**/*.py"],
        denied=["src/private/**"],
    )

    assert policy.allows("reports/summary.txt")
    assert not policy.allows("reports/nested/summary.txt")
    assert policy.allows("src/app.py")
    assert policy.allows("src/pkg/app.py")
    assert not policy.allows("src/pkg/app.txt")
    assert not policy.allows("src/private/token.py")
    assert path_matches_pattern("src/pkg/app.py", "src/**/*.py")
    assert not path_matches_pattern("reports/nested/summary.txt", "reports/*.txt")


def test_batch_decision_reports_relative_violating_paths(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    policy = PathPolicy(root, allowed=["src/**"], denied=["src/private/**"])

    decision = policy.check_paths(["src/app.py", "src/private/token.txt", "README.md"])

    assert not decision.allowed
    assert decision.violating_paths == ("src/private/token.txt", "README.md")
    assert decision.to_dict()["violating_paths"] == ["src/private/token.txt", "README.md"]
