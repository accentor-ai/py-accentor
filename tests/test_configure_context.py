from __future__ import annotations

import json

from accentor.configure import ConfigureContext, ContextSelector
from accentor.configure.context import user_call_args


def assert_json_stable(payload: dict) -> dict:
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    return json.loads(encoded)


def test_configure_context_serializes_selected_value_and_copies_metadata() -> None:
    metadata = {"source": "fixture"}
    context = ConfigureContext(
        {"topic": "privacy"},
        name="policy",
        source="static",
        user_input={"prompt": "keep", "ctx": object(), "success_criteria": "hidden"},
        metadata=metadata,
    )
    metadata["source"] = "mutated"

    payload = assert_json_stable(context.to_dict())

    assert payload["name"] == "policy"
    assert payload["value"] == {"topic": "privacy"}
    assert payload["metadata"] == {"source": "fixture"}
    assert payload["user_input"] == {"prompt": "keep"}


def test_static_selector_is_deterministic_and_does_not_mutate_call_args() -> None:
    call_args = {"customer": "A", "ctx": object()}
    selector = ContextSelector.static({"audience": "internal"}, name="audience")

    first = selector.select(call_args)
    second = selector(call_args)

    assert first.to_dict() == second.to_dict()
    assert first.value == {"audience": "internal"}
    assert first.user_input == {"customer": "A"}
    assert "ctx" in call_args


def test_list_selector_preserves_order_without_selection_key() -> None:
    selector = ContextSelector.from_list(["alpha", "beta"], name="candidates")

    context = selector.select({"routed_context": "framework"})

    assert context.value == ["alpha", "beta"]
    assert context.selected_index is None
    assert context.user_input == {}
    assert_json_stable(context.to_dict())


def test_list_selector_can_select_by_call_time_index_or_value() -> None:
    selector = ContextSelector.from_list(["alpha", "beta"], selection_key="choice")

    by_index = selector.select({"choice": 1})
    by_value = selector.select({"choice": "alpha"})

    assert by_index.value == "beta"
    assert by_index.selected_index == 1
    assert by_value.value == "alpha"
    assert by_value.selected_index == 0


def test_call_arg_selector_uses_default_and_excludes_framework_values() -> None:
    selector = ContextSelector.from_call_arg("topic", default="fallback", metadata={"kind": "demo"})

    context = selector.select({"ctx": object(), "success_criteria": "hidden"})

    assert context.value == "fallback"
    assert context.source == "call_arg:topic"
    assert context.user_input == {}
    assert context.metadata == {"kind": "demo"}


def test_user_call_args_filters_framework_injected_names() -> None:
    assert user_call_args(
        {
            "topic": "shipping",
            "ctx": "runtime",
            "routed_context": "route",
            "success_criteria": "criteria",
        }
    ) == {"topic": "shipping"}
