from __future__ import annotations

import json

import httpx

from app.tools.api_client import ApiClient
from app.tools.handlers import handle_tool_call
from tests.helpers.api_mock import FakeApi


def _routed(map_: dict[str, dict]) -> FakeApi:
    def respond(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=map_[req.url.path])

    return FakeApi(respond)


def _client(api: FakeApi) -> ApiClient:
    return ApiClient(
        base_url="http://api.local",
        secret="s" * 32,
        tenant="spicy-desi",
        transport=api.transport(),
    )


async def test_get_pickup_today_returns_serialized_json() -> None:
    api = _routed({"/api/pickup/today": {"pickup": {"name": "29th"}}})
    c = _client(api)
    try:
        result = await handle_tool_call("get_pickup_today", {}, api=c, call_sid="CA1")
    finally:
        await c.aclose()
    assert json.loads(result) == {"pickup": {"name": "29th"}}


async def test_search_menu_uses_query_arg() -> None:
    api = _routed({"/api/menu/search": {"items": [{"name": "Momos"}]}})
    c = _client(api)
    try:
        result = await handle_tool_call("search_menu", {"query": "momos"}, api=c, call_sid="CA1")
    finally:
        await c.aclose()
    assert "Momos" in result


async def test_get_specials() -> None:
    api = _routed({"/api/specials": {"items": [{"name": "Pani Puri"}]}})
    c = _client(api)
    try:
        result = await handle_tool_call("get_specials", {}, api=c, call_sid="CA1")
    finally:
        await c.aclose()
    assert "Pani Puri" in result


async def test_take_message_passes_call_sid_and_required_args() -> None:
    api = _routed({"/api/messages": {"ok": True, "sms_sent": True}})
    c = _client(api)
    try:
        result = await handle_tool_call(
            "take_message",
            {"callback_number": "+13125551111", "reason": "catering"},
            api=c,
            call_sid="CA42",
        )
    finally:
        await c.aclose()
    assert json.loads(result)["ok"] is True
    body = json.loads(api.requests[0].content)
    assert body["call_sid"] == "CA42"


async def test_request_transfer() -> None:
    api = _routed({"/api/transfers": {"action": "take_message"}})
    c = _client(api)
    try:
        result = await handle_tool_call(
            "request_transfer", {"reason": "needs owner"}, api=c, call_sid="CA1"
        )
    finally:
        await c.aclose()
    assert json.loads(result)["action"] == "take_message"


async def test_unknown_tool_returns_error_payload() -> None:
    api = _routed({})
    c = _client(api)
    try:
        result = await handle_tool_call("nope", {}, api=c, call_sid="CA1")
    finally:
        await c.aclose()
    assert "unknown tool" in json.loads(result)["error"]
