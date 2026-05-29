from __future__ import annotations

import pytest

from accentor.core.decorators import (
    StageConfigurationError,
    StageValidationError,
    stage,
)
from accentor.dispatch.agents.providers.mock import MockAgent


def _validator(candidate: object) -> bool:
    return bool(candidate)


def test_agent_execution_requires_adapter_with_run_method() -> None:
    with pytest.raises(StageConfigurationError) as error:

        @stage(name="draft_reply", execution="agent")
        def draft_reply() -> str:
            return "Return JSON."

    assert error.value.stage_name == "draft_reply"
    assert error.value.area == "agent"
    assert "agent" in error.value.missing_fields
    assert "Stage 'draft_reply' is missing required agent configuration:" in str(error.value)
    assert "Example:" in str(error.value)


def test_prompt_only_agent_stage_without_file_scope_is_valid() -> None:
    agent = MockAgent(responses=['{"ok": true}'])

    @stage(name="prompt_only", agent=agent)
    def prompt_only() -> str:
        return "Return JSON."

    config = prompt_only.__accentor_stage_config__

    assert config.execution == "agent"
    assert config.readable == ()
    assert config.editable == ()
    assert config.network is None


def test_repair_policy_without_agent_fails_at_configuration_time() -> None:
    with pytest.raises(StageConfigurationError) as error:

        @stage(
            name="parse_orders",
            readable=["orders.csv"],
            editable=["parser.py"],
            on_error={
                ValueError: {
                    "response": "agent_repair",
                    "goal": "Repair CSV parsing.",
                    "validators": [_validator],
                }
            },
        )
        def parse_orders() -> list[dict[str, str]]:
            return []

    assert error.value.area == "repair"
    assert error.value.missing_fields == ("agent",)
    assert "Stage 'parse_orders' is missing required repair configuration: agent." in str(error.value)
    assert "on_error={ValueError:" in str(error.value)


def test_repair_policy_requires_response_goal_scope_and_validators() -> None:
    with pytest.raises(StageConfigurationError) as error:

        @stage(
            name="parse_orders",
            on_error={ValueError: {"agent": MockAgent()}},
        )
        def parse_orders() -> list[dict[str, str]]:
            return []

    assert error.value.missing_fields == (
        "response",
        "goal/prompt",
        "readable",
        "editable",
        "validators",
    )


def test_valid_repair_policy_inherits_stage_scope_and_keeps_local_happy_path() -> None:
    agent = MockAgent(responses=["plain repair text must not imply success"])

    @stage(
        name="parse_orders",
        readable=["orders.csv"],
        editable=["parser.py"],
        on_error={
            ValueError: {
                "response": "agent_repair",
                "agent": agent,
                "goal": "Repair CSV parsing.",
                "validators": [_validator],
            }
        },
    )
    def parse_orders() -> str:
        return "ok"

    config = parse_orders.__accentor_stage_config__
    repair_policy = config.repair_policies[0]

    assert parse_orders() == "ok"
    assert config.execution == "local"
    assert repair_policy.agent is agent
    assert repair_policy.readable == ("orders.csv",)
    assert repair_policy.editable == ("parser.py",)
    assert repair_policy.validators == (_validator,)
    assert agent.run_count == 0


def test_repair_stub_reports_unsupported_instead_of_claiming_mock_success() -> None:
    agent = MockAgent(responses=["I fixed it"])

    @stage(
        name="parse_orders",
        readable=["orders.csv"],
        editable=["parser.py"],
        on_error={
            ValueError: {
                "response": "agent_repair",
                "agent": agent,
                "goal": "Repair CSV parsing.",
                "validators": [_validator],
            }
        },
    )
    def parse_orders() -> str:
        raise ValueError("bad delimiter")

    with pytest.raises(StageValidationError, match="repair execution is not implemented"):
        parse_orders()

    assert agent.run_count == 0


@pytest.mark.parametrize(
    ("kwargs", "area", "field"),
    [
        ({"readable": True}, "file", "readable"),
        ({"editable": True}, "write", "editable"),
        ({"network": {}}, "network", "enabled/search/hosts"),
        ({"observation": True}, "sensitive-observation", "observation"),
    ],
)
def test_underspecified_risky_declarations_fail_with_examples(
    kwargs: dict[str, object],
    area: str,
    field: str,
) -> None:
    with pytest.raises(StageConfigurationError) as error:

        @stage(name="risky_stage", **kwargs)
        def risky_stage() -> str:
            return "ok"

    assert error.value.stage_name == "risky_stage"
    assert error.value.area == area
    assert field in error.value.missing_fields
    assert str(error.value).startswith(
        f"Stage 'risky_stage' is missing required {area} configuration:"
    )
    assert "Example:" in str(error.value)


def test_explicit_network_and_sensitive_observation_declarations_are_valid() -> None:
    @stage(name="search_stage", network={"search": True}, observation="sensitive")
    def search_stage() -> str:
        return "ok"

    config = search_stage.__accentor_stage_config__

    assert config.network == {"search": True}
    assert config.observation == "sensitive"
