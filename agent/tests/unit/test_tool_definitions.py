from __future__ import annotations

from app.tools.definitions import TOOL_DEFINITIONS

EXPECTED_NAMES = {
    "get_pickup_today",
    "search_menu",
    "list_full_menu",
    "list_menu_categories",
    "get_specials",
    "send_order_link",
    "send_location_link",
    "take_message",
    "request_transfer",
}


def test_all_expected_tools_defined() -> None:
    names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    assert names == EXPECTED_NAMES


def test_each_tool_is_well_formed() -> None:
    for tool in TOOL_DEFINITIONS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert isinstance(fn["name"], str) and fn["name"]
        assert isinstance(fn["description"], str) and fn["description"]
        params = fn["parameters"]
        assert params["type"] == "object"
        assert isinstance(params.get("properties", {}), dict)
        assert isinstance(params.get("required", []), list)


def test_required_args_present_for_take_message() -> None:
    take_msg = next(t for t in TOOL_DEFINITIONS if t["function"]["name"] == "take_message")
    required = take_msg["function"]["parameters"]["required"]
    assert "callback_number" in required
    assert "reason" in required
