from __future__ import annotations

"""Shared record-contract fixtures for the workpackage test suite.

These fixtures intentionally avoid importing Accentor provider modules. They
pin the JSON field names shared by WP-01/WP-02 tests while leaving product
behavior in the package modules under test.
"""

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest


JsonPayload = dict[str, Any]
JsonStableAssert = Callable[[Any], Any]


@dataclass(frozen=True)
class PathSafetyWorkspace:
    """Temporary paths for root-confined path-safety tests."""

    root: Path
    outside: Path
    allowed_file: Path
    outside_file: Path
    symlink_escape: Path | None


def _assert_json_stable(payload: Any) -> Any:
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded == payload
    assert json.dumps(decoded, allow_nan=False, sort_keys=True) == encoded
    return decoded


@pytest.fixture
def artifact_root(tmp_path: Path) -> Path:
    root = tmp_path / "artifacts"
    root.mkdir()
    return root


@pytest.fixture
def path_safety_workspace(tmp_path: Path) -> PathSafetyWorkspace:
    workspace = tmp_path / "path_safety"
    root = workspace / "root"
    outside = workspace / "outside"
    root.mkdir(parents=True)
    outside.mkdir(parents=True)

    allowed_file = root / "nested" / "allowed.txt"
    allowed_file.parent.mkdir()
    allowed_file.write_text("allowed", encoding="utf-8")

    outside_file = outside / "escape.txt"
    outside_file.write_text("outside", encoding="utf-8")

    symlink_escape = root / "linked_outside"
    try:
        symlink_escape.symlink_to(outside, target_is_directory=True)
    except OSError:
        symlink_escape = None

    return PathSafetyWorkspace(
        root=root,
        outside=outside,
        allowed_file=allowed_file,
        outside_file=outside_file,
        symlink_escape=symlink_escape,
    )


@pytest.fixture
def sample_diagnostic_payload() -> JsonPayload:
    return {
        "code": "validation.missing_field",
        "message": "Output did not include a required field.",
        "severity": "warning",
        "source": "validator",
        "hint": "Return a JSON object with all required fields.",
        "details": {
            "field": "answer",
            "redacted": True,
            "secret_ref": "env:API_TOKEN",
        },
    }


@pytest.fixture
def sample_task_event_payload(sample_diagnostic_payload: JsonPayload) -> JsonPayload:
    return {
        "event_type": "stage.completed",
        "timestamp": "2026-05-28T00:00:00+00:00",
        "workflow": "support_triage",
        "task": "draft_response",
        "stage": "validate_output",
        "attempt": 0,
        "status": "validated",
        "message": "Stage completed with accepted output.",
        "diagnostics": [copy.deepcopy(sample_diagnostic_payload)],
        "artifacts": [
            {
                "name": "validation_report.json",
                "path": "validation_report.json",
                "kind": "validation_report",
            }
        ],
        "validation": {"ok": True, "validator": "json_fields"},
        "routing": None,
        "repair": None,
        "details": {
            "redacted": True,
            "secret_ref": "env:API_TOKEN",
        },
    }


@pytest.fixture
def assert_json_stable() -> JsonStableAssert:
    return _assert_json_stable


__all__ = [
    "PathSafetyWorkspace",
]
