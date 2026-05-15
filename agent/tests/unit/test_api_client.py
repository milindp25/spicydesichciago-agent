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


import json
from datetime import datetime, timezone


async def test_record_call_start_posts_to_start_route() -> None:
    api = FakeApi(json_responder({"ok": True}))
    c = _client(api)
    try:
        await c.record_call_start(
            call_sid="CA1",
            started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
            caller_phone="+15551234567",
            from_number="+15559998888",
        )
    finally:
        await c.aclose()
    req = api.requests[-1]
    assert req.url.path == "/api/calls/CA1/start"
    assert req.method == "POST"
    body = json.loads(req.content)
    assert body["caller_phone"] == "+15551234567"
    assert body["from_number"] == "+15559998888"
    assert body["started_at"].startswith("2026-05-14T12:00:00")


async def test_record_call_end_posts_end_route() -> None:
    api = FakeApi(json_responder({"ok": True}))
    c = _client(api)
    try:
        await c.record_call_end(
            call_sid="CA1",
            ended_at=datetime(2026, 5, 14, 12, 1, 30, tzinfo=timezone.utc),
            outcome="resolved",
            duration_ms=90000,
        )
    finally:
        await c.aclose()
    req = api.requests[-1]
    assert req.url.path == "/api/calls/CA1/end"
    body = json.loads(req.content)
    assert body["outcome"] == "resolved"
    assert body["duration_ms"] == 90000


async def test_record_call_summary_posts_summary_route() -> None:
    api = FakeApi(json_responder({"ok": True}))
    c = _client(api)
    try:
        await c.record_call_summary(
            call_sid="CA1",
            summary="Asked about hours and momos; sent order link",
        )
    finally:
        await c.aclose()
    req = api.requests[-1]
    assert req.url.path == "/api/calls/CA1/summary"
    body = json.loads(req.content)
    assert body["summary"] == "Asked about hours and momos; sent order link"


async def test_record_call_transcript_posts_turns() -> None:
    api = FakeApi(json_responder({"ok": True, "turn_count": 2}, status_code=202))
    c = _client(api)
    try:
        await c.record_call_transcript(
            call_sid="CA1",
            turns=[
                {"role": "caller", "text": "hi"},
                {"role": "agent", "text": "hello"},
            ],
        )
    finally:
        await c.aclose()
    req = api.requests[-1]
    assert req.url.path == "/api/calls/CA1/transcript"
    assert req.method == "POST"
    body = json.loads(req.content)
    assert body["turns"][0] == {"role": "caller", "text": "hi"}
    assert body["turns"][1] == {"role": "agent", "text": "hello"}


async def test_record_call_transcript_swallows_errors() -> None:
    """Best-effort: a 500 from the API must not raise."""
    import httpx

    def failing_responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    api = FakeApi(failing_responder)
    c = _client(api)
    try:
        # Must not raise
        await c.record_call_transcript(
            call_sid="CA1",
            turns=[{"role": "caller", "text": "hi"}],
        )
    finally:
        await c.aclose()


async def test_lifecycle_methods_swallow_http_errors() -> None:
    """Returns 500 — methods must not raise (best-effort, called on hangup)."""
    import httpx

    def failing_responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    api = FakeApi(failing_responder)
    c = _client(api)
    try:
        await c.record_call_start(
            call_sid="CA1",
            started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
            caller_phone="+15551234567",
            from_number="+15559998888",
        )
        await c.record_call_end(
            call_sid="CA1",
            ended_at=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
            outcome="failed",
            duration_ms=60000,
        )
        await c.record_call_summary(call_sid="CA1", summary="test")
    finally:
        await c.aclose()
