from __future__ import annotations

import json
from pathlib import Path

from accentor.core.steps import Phase
from accentor.core.task import Task, TaskDefinition, TaskId, TaskVersionId
from accentor.dispatch.agents.providers.mock import MockAgent
from accentor.evaluate.validation import ExactFinalMessage, JsonFieldEquals, JsonRequired


def test_task_definition_records_are_serializable() -> None:
    definition = TaskDefinition(
        name="read_check",
        task_id=TaskId("read-check"),
        version_id=TaskVersionId("2026-05-28"),
        phases=[Phase(name="ready", prompt="Return READY.")],
        metadata={"kind": "phase_runner"},
    )

    assert definition.to_dict() == {
        "task_id": "read-check",
        "version_id": "2026-05-28",
        "name": "read_check",
        "description": None,
        "phases": [Phase(name="ready", prompt="Return READY.").to_dict()],
        "metadata": {"kind": "phase_runner"},
    }


def test_unsupported_persistence_returns_diagnostic_without_dispatch() -> None:
    agent = MockAgent(responses=["READY", "{}"])
    task = Task(
        name="needs_persistence",
        agent=agent,
        phases=[
            Phase(name="read", prompt="Return READY."),
            Phase(name="answer", prompt="Return JSON."),
        ],
    )

    result = task.run()

    assert result.ok is False
    assert agent.run_count == 0
    assert result.diagnostics[0].code == "task.persistence_unsupported"
    assert result.diagnostics[0].details["phase_count"] == 2


def test_phase_runner_executes_phases_in_order_and_returns_final_output(tmp_path: Path) -> None:
    guidelines = tmp_path / "guidelines.txt"
    challenge = tmp_path / "challenge_public.json"
    guidelines.write_text("Remember alpha.", encoding="utf-8")
    challenge.write_text("{}", encoding="utf-8")
    agent = MockAgent(
        responses=[
            "READY",
            '{"answer": "alpha", "evidence_source": "session_memory"}',
        ],
        session="persistent",
    )
    task = Task(
        name="ordered_phases",
        agent=agent,
        phases=[
            Phase(
                name="read_guidelines",
                prompt="Read guidelines.txt and return READY.",
                workspace_files=[guidelines],
                validators=[ExactFinalMessage("READY")],
            ),
            Phase(
                name="memory_challenge",
                prompt="Return answer JSON.",
                workspace_files=[challenge],
                revoke_files=[guidelines],
                validators=[
                    JsonRequired(keys=["answer", "evidence_source"]),
                    JsonFieldEquals(field="evidence_source", value="session_memory"),
                ],
            ),
        ],
    )

    result = task.run(artifact_root=tmp_path / "artifacts")

    assert result.ok is True
    assert result.output == {"answer": "alpha", "evidence_source": "session_memory"}
    assert result.best_output == result.output
    assert result.attempt_count == 2
    assert [request.prompt for request in agent.requests] == [
        "Read guidelines.txt and return READY.",
        "Return answer JSON.",
    ]
    assert (tmp_path / "artifacts" / "task_result.json").is_file()


def test_phase_validation_failure_preserves_best_output(tmp_path: Path) -> None:
    agent = MockAgent(responses=["READY", "not json"], session="persistent")
    task = Task(
        name="validation_failure",
        agent=agent,
        phases=[
            Phase(name="read", prompt="Return READY.", validators=[ExactFinalMessage("READY")]),
            Phase(name="answer", prompt="Return JSON.", validators=[JsonRequired(keys=["answer"])]),
        ],
    )

    result = task.run(artifact_root=tmp_path)

    assert result.ok is False
    assert result.output is None
    assert result.best_output == "not json"
    assert result.attempt_count == 2
    assert any(diagnostic.code == "validation.exhausted" for diagnostic in result.diagnostics)


def test_revoked_files_are_absent_from_next_phase_workspace(tmp_path: Path) -> None:
    guidelines = tmp_path / "task_guidelines.txt"
    challenge = tmp_path / "challenge_public.json"
    guidelines.write_text("secret source text", encoding="utf-8")
    challenge.write_text(json.dumps({"question": "public"}), encoding="utf-8")
    agent = MockAgent(
        responses=[
            "READY",
            '{"answer": "source text", "evidence_source": "session_memory"}',
        ],
        session="persistent",
    )
    task = Task(
        name="revocation",
        agent=agent,
        phases=[
            Phase(name="read", prompt="Read task_guidelines.txt.", workspace_files=[guidelines]),
            Phase(
                name="challenge",
                prompt="Answer.",
                workspace_files=[challenge],
                revoke_files=[guidelines],
                validators=[JsonRequired(keys=["answer", "evidence_source"])],
            ),
        ],
    )

    result = task.run()

    assert result.ok is True
    second_workspace = agent.requests[1].workspace
    assert second_workspace is not None
    assert "task_guidelines.txt" not in second_workspace.list_files()
    assert "challenge_public.json" in second_workspace.list_files()
    assert not (second_workspace.root / "task_guidelines.txt").exists()
    assert agent.requests[1].permissions["revoked"] == ["task_guidelines.txt"]
