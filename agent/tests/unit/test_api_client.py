from __future__ import annotations

from app.tools.api_client import ApiClient
from tests.helpers.api_mock import FakeApi, json_responder


def _client(api: FakeApi) -> ApiClient:
    return ApiClient(
        base_url="http://api.local",
        secret="s" * 32,
        tenant="spicy-desi",
        transport=api.transport(),
    )


async def test_get_pickup_today_passes_tenant_and_returns_json() -> None:
    api = FakeApi(json_responder({"pickup": {"name": "29th Street"}}))
    c = _client(api)
    try:
        result = await c.get_pickup_today()
    finally:
        await c.aclose()
    assert result == {"pickup": {"name": "29th Street"}}
    req = api.requests[0]
    assert req.url.path == "/api/pickup/today"
    assert dict(req.url.params) == {"tenant": "spicy-desi"}
    assert req.headers["x-tools-auth"] == "s" * 32


async def test_search_menu_query_is_passed() -> None:
    api = FakeApi(json_responder({"items": []}))
    c = _client(api)
    try:
        await c.search_menu("momos")
    finally:
        await c.aclose()
    req = api.requests[0]
    assert req.url.path == "/api/menu/search"
    assert dict(req.url.params) == {"tenant": "spicy-desi", "q": "momos"}


async def test_list_full_menu_passes_tenant() -> None:
    api = FakeApi(json_responder({"items": [{"name": "Pani Puri", "category": "Chaat"}]}))
    c = _client(api)
    try:
        result = await c.list_full_menu()
    finally:
        await c.aclose()
    assert result["items"][0]["name"] == "Pani Puri"
    req = api.requests[0]
    assert req.url.path == "/api/menu/list"
    assert dict(req.url.params) == {"tenant": "spicy-desi"}


async def test_get_specials() -> None:
    api = FakeApi(json_responder({"items": [{"name": "Pani Puri"}]}))
    c = _client(api)
    try:
        result = await c.get_specials()
    finally:
        await c.aclose()
    assert result["items"][0]["name"] == "Pani Puri"
    assert api.requests[0].url.path == "/api/specials"


async def test_take_message_posts_full_body() -> None:
    api = FakeApi(json_responder({"ok": True, "sms_sent": True}, status_code=202))
    c = _client(api)
    try:
        result = await c.take_message(
            call_sid="CA1",
            callback_number="+13125551111",
            reason="catering for 25",
            caller_name="Asha",
        )
    finally:
        await c.aclose()
    assert result["ok"] is True
    req = api.requests[0]
    assert req.url.path == "/api/messages"
    import json

    body = json.loads(req.content)
    assert body["call_sid"] == "CA1"
    assert body["callback_number"] == "+13125551111"
    assert body["reason"] == "catering for 25"
    assert body["caller_name"] == "Asha"


async def test_request_transfer_posts_call_sid() -> None:
    api = FakeApi(json_responder({"action": "transfer", "redirect_ok": True}))
    c = _client(api)
    try:
        result = await c.request_transfer(call_sid="CA9", reason="needs owner")
    finally:
        await c.aclose()
    assert result["action"] == "transfer"
    req = api.requests[0]
    assert req.url.path == "/api/transfers"
    import json

    body = json.loads(req.content)
    assert body == {"call_sid": "CA9", "reason": "needs owner"}
