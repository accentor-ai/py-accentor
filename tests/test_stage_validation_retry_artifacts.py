from __future__ import annotations

import json
from pathlib import Path

from accentor.core.decorators import stage, workflow
from accentor.dispatch.agents.providers.mock import MockAgent
from accentor.evaluate.validation import FileRequiredKeys, JsonRequired, NoMarkdownFences, RequiredFile


def _artifact_names(result: object) -> set[str]:
    names: set[str] = set()
    for artifact in getattr(result, "artifacts", ()):
        if hasattr(artifact, "name"):
            names.add(artifact.name)
        else:
            names.add(str(artifact["name"]))
    return names


def test_local_stage_validates_return_value_and_writes_validation_artifacts(tmp_path: Path) -> None:
    @stage(validators=[JsonRequired(keys=["ok"])])
    def local_json() -> str:
        return '{"ok": true}'

    @workflow(name="local_validation")
    def local_validation() -> dict:
        return local_json()

    result = local_validation(artifact_root=tmp_path)

    assert result.ok is True
    assert result.output == {"ok": True}
    assert result.attempt_count == 1
    assert (tmp_path / "validation_report.json").is_file()
    assert (tmp_path / "validation_report_attempt_0.json").is_file()
    assert {"events.jsonl", "task_result.json", "validation_report.json"} <= _artifact_names(result)


def test_local_file_validators_run_after_function_creates_file(tmp_path: Path) -> None:
    output_file = tmp_path / "summary.json"

    @stage(validators=[RequiredFile(output_file), FileRequiredKeys(output_file, keys=["count"])])
    def write_summary() -> dict[str, int]:
        output_file.write_text(json.dumps({"count": 3}), encoding="utf-8")
        return {"count": 3}

    @workflow(name="file_validation")
    def file_validation() -> dict[str, int]:
        return write_summary()

    result = file_validation(artifact_root=tmp_path / "artifacts")

    assert result.ok is True
    assert result.output == {"count": 3}
    assert (tmp_path / "artifacts" / "validation_report.json").is_file()


def test_agent_stage_extracts_json_retries_and_records_prompt_attempts(tmp_path: Path) -> None:
    agent = MockAgent(responses=["not json", '{"must_exist": true}'])

    @stage(
        name="retry_json",
        agent=agent,
        validators=[NoMarkdownFences(), JsonRequired(keys=["must_exist"])],
        max_attempts=2,
        inject_criteria=True,
    )
    def retry_json(success_criteria: str = "") -> str:
        return f"Return JSON only.\n\n{success_criteria}"

    @workflow(name="retry_workflow")
    def retry_workflow() -> dict:
        return retry_json()

    result = retry_workflow(artifact_root=tmp_path)

    assert result.ok is True
    assert result.output == {"must_exist": True}
    assert result.attempt_count == 2
    assert agent.run_count == 2
    assert "Previous validation failures:" in agent.requests[1].prompt
    assert (tmp_path / "prompt_attempt_0.md").is_file()
    assert (tmp_path / "prompt_attempt_1.md").is_file()
    assert (tmp_path / "validation_report_attempt_1.json").is_file()
    assert "prompt_attempt_1.md" in _artifact_names(result)


def test_exhausted_validation_returns_failed_task_result_with_best_output(tmp_path: Path) -> None:
    agent = MockAgent(responses=["not json", "still not json"])

    @stage(
        name="impossible_json",
        agent=agent,
        validators=[NoMarkdownFences(), JsonRequired(keys=["must_exist"])],
        max_attempts=2,
        inject_criteria=True,
    )
    def impossible_json(success_criteria: str = "") -> str:
        return f"Return JSON with must_exist.\n\n{success_criteria}"

    @workflow(name="expected_failure")
    def expected_failure() -> dict:
        return impossible_json()

    result = expected_failure(artifact_root=tmp_path)

    assert result.ok is False
    assert result.output is None
    assert result.best_output == "still not json"
    assert result.attempt_count == 2
    assert any(diagnostic.code == "validation.exhausted" for diagnostic in result.diagnostics)
    assert json.loads((tmp_path / "task_result.json").read_text(encoding="utf-8"))["ok"] is False


def test_direct_stage_with_validators_returns_task_result(tmp_path: Path) -> None:
    @stage(validators=[JsonRequired(keys=["value"])])
    def direct_json() -> str:
        return '{"value": 1}'

    result = direct_json(artifact_root=tmp_path)

    assert result.ok is True
    assert result.output == {"value": 1}
    assert (tmp_path / "events.jsonl").is_file()
    assert (tmp_path / "task_result.json").is_file()
