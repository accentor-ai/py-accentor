from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from accentor.core.steps import Phase
from accentor.evaluate.validation import ExactFinalMessage, JsonFieldEquals, JsonRequired, Validator


def test_phase_defaults_are_safe_and_serializable(assert_json_stable: Callable[[Any], Any]) -> None:
    phase = Phase(name="prompt_only", prompt="Return READY.")

    assert phase.name == "prompt_only"
    assert phase.prompt == "Return READY."
    assert phase.workspace_files == ()
    assert phase.readable_files == ()
    assert phase.revoke_files == ()
    assert phase.revoked_files == ()
    assert phase.editable_files == ()
    assert phase.network is False
    assert phase.validators == ()
    assert phase.metadata == {}

    payload = assert_json_stable(phase.to_dict())
    assert payload == {
        "name": "prompt_only",
        "prompt": "Return READY.",
        "workspace_files": [],
        "revoke_files": [],
        "editable_files": [],
        "network": False,
        "validators": [],
        "metadata": {},
    }
    assert json.loads(phase.to_json()) == payload


def test_phase_preserves_prompt_text_and_ordered_file_lists(tmp_path: Path) -> None:
    guidelines = tmp_path / "inputs" / "task_guidelines.txt"
    public_challenge = tmp_path / "challenge_public.json"
    prompt = """
        Read task_guidelines.txt carefully.
        Reply exactly READY.
    """

    phase = Phase(
        name="read_guidelines",
        prompt=prompt,
        workspace_files=[guidelines, public_challenge, guidelines],
        revoke_files=[guidelines],
    )

    assert phase.prompt is prompt
    assert phase.workspace_files == (guidelines, public_challenge)
    assert phase.readable_files == phase.workspace_files
    assert phase.revoke_files == (guidelines,)
    assert phase.revoked_files == phase.revoke_files
    assert phase.to_dict()["workspace_files"] == [str(guidelines), str(public_challenge)]
    assert phase.to_dict()["revoke_files"] == [str(guidelines)]


def test_phase_stores_validators_without_leaking_validator_state() -> None:
    class SecretAnswerValidator(Validator):
        def __init__(self) -> None:
            self.expected_answer = "verifier-secret-answer"

        def check(self, output: Any) -> list[str]:
            return [] if output == self.expected_answer else ["incorrect answer"]

    phase = Phase(
        name="memory_challenge",
        prompt="Answer from session memory.",
        validators=[
            JsonRequired(keys=["answer", "evidence_source"]),
            JsonFieldEquals(field="evidence_source", value="session_memory"),
            SecretAnswerValidator(),
        ],
        metadata={
            "kind": "read_verification",
            "attempts": 1,
        },
    )

    assert phase.validators[0].__class__ is JsonRequired
    assert phase.validator_names == ("JsonRequired", "JsonFieldEquals", "SecretAnswerValidator")

    encoded = phase.to_json()
    assert "SecretAnswerValidator" in encoded
    assert "verifier-secret-answer" not in encoded
    assert json.loads(encoded)["validators"] == [
        "JsonRequired",
        "JsonFieldEquals",
        "SecretAnswerValidator",
    ]


def test_phase_metadata_is_json_stable_and_immutable(tmp_path: Path) -> None:
    metadata = {
        "source": tmp_path / "inputs" / "task_guidelines.txt",
        "labels": {"memory", "read"},
        "nested": {"enabled": True},
    }
    phase = Phase(name="with_metadata", prompt="Return READY.", metadata=metadata)
    metadata["nested"] = {"enabled": False}

    assert phase.metadata["nested"] == {"enabled": True}
    assert phase.to_dict()["metadata"] == {
        "source": str(tmp_path / "inputs" / "task_guidelines.txt"),
        "labels": ["memory", "read"],
        "nested": {"enabled": True},
    }
    with pytest.raises(TypeError):
        phase.metadata["new"] = "value"  # type: ignore[index]


def test_p0_06_two_phase_shape_needs_no_extra_boilerplate(tmp_path: Path) -> None:
    guidelines = tmp_path / "task_guidelines.txt"
    challenge_public = tmp_path / "challenge_public.json"

    phases = [
        Phase(
            name="read_guidelines",
            prompt="Read task_guidelines.txt carefully and reply READY.",
            workspace_files=[guidelines],
            validators=[ExactFinalMessage("READY")],
        ),
        Phase(
            name="memory_challenge",
            prompt="Return JSON with answer and evidence_source.",
            workspace_files=[challenge_public],
            revoke_files=[guidelines],
            validators=[
                JsonRequired(keys=["answer", "evidence_source"]),
                JsonFieldEquals(field="evidence_source", value="session_memory"),
            ],
        ),
    ]

    assert [phase.name for phase in phases] == ["read_guidelines", "memory_challenge"]
    assert phases[0].workspace_files == (guidelines,)
    assert phases[1].workspace_files == (challenge_public,)
    assert phases[1].revoke_files == (guidelines,)
    assert phases[0].validator_names == ("ExactFinalMessage",)
    assert phases[1].validator_names == ("JsonRequired", "JsonFieldEquals")


def test_phase_rejects_invalid_constructor_inputs() -> None:
    with pytest.raises(ValueError, match="phase name"):
        Phase(name="", prompt="Return READY.")
    with pytest.raises(TypeError, match="prompt"):
        Phase(name="bad_prompt", prompt=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="validators"):
        Phase(name="bad_validators", prompt="Return READY.", validators="JsonRequired")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="paths"):
        Phase(name="bad_path", prompt="Return READY.", workspace_files=[""])


def test_phase_export_surface() -> None:
    from accentor.core.steps import Phase as ExportedPhase

    assert ExportedPhase is Phase
