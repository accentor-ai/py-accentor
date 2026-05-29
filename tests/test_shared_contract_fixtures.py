from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from tests.conftest import PathSafetyWorkspace


EXPECTED_DIAGNOSTIC_FIELDS = {
    "code",
    "message",
    "severity",
    "source",
    "hint",
    "details",
}

EXPECTED_EVENT_FIELDS = {
    "event_type",
    "timestamp",
    "workflow",
    "task",
    "stage",
    "attempt",
    "status",
    "message",
    "diagnostics",
    "artifacts",
    "validation",
    "routing",
    "repair",
    "details",
}


def test_shared_record_fixtures_pin_json_stable_fields(
    artifact_root: Path,
    path_safety_workspace: PathSafetyWorkspace,
    sample_diagnostic_payload: dict[str, Any],
    sample_task_event_payload: dict[str, Any],
    assert_json_stable: Callable[[Any], Any],
) -> None:
    diagnostic = assert_json_stable(sample_diagnostic_payload)
    event = assert_json_stable(sample_task_event_payload)

    assert artifact_root.is_dir()
    assert artifact_root.name == "artifacts"

    assert path_safety_workspace.root.is_dir()
    assert path_safety_workspace.allowed_file.is_relative_to(path_safety_workspace.root)
    assert not path_safety_workspace.outside_file.is_relative_to(path_safety_workspace.root)

    assert set(diagnostic) == EXPECTED_DIAGNOSTIC_FIELDS
    assert diagnostic["severity"] == "warning"
    assert diagnostic["details"]["secret_ref"] == "env:API_TOKEN"

    assert set(event) == EXPECTED_EVENT_FIELDS
    assert event["diagnostics"] == [diagnostic]
    assert event["artifacts"][0]["name"] == "validation_report.json"
    assert event["validation"] == {"ok": True, "validator": "json_fields"}
    assert "provider" not in event


def test_shared_fixture_module_import_does_not_import_live_providers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    code = """
import json
import sys

import tests.conftest

print(json.dumps([
    name for name in sorted(sys.modules)
    if name == "accentor.dispatch.agents.providers"
    or name.startswith("accentor.dispatch.agents.providers.")
]))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == []
