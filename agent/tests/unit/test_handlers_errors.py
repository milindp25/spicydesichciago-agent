"""Tests for handler error paths — every tool should return voice_fallback
on API failure instead of raising."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.tools.handlers import handle_tool_call


class _BoomApi:
    """ApiClient stub where every method raises httpx.TimeoutException."""
    def __getattr__(self, name: str):
        async def _boom(*a, **kw):
            raise httpx.TimeoutException("read timeout")
        return _boom


@pytest.mark.asyncio
async def test_get_pickup_today_returns_fallback_on_timeout():
    result = await handle_tool_call(
        "get_pickup_today", {}, api=_BoomApi(), call_sid="CA1"
    )
    data = json.loads(result)
    assert "error" in data
    assert "voice_fallback" in data
    # Generic fallback OK for get_pickup_today since the tool spans hours+address+location
    assert len(data["voice_fallback"]) > 0


@pytest.mark.asyncio
async def test_search_menu_uses_menu_specific_fallback():
    result = await handle_tool_call(
        "search_menu", {"query": "biryani"}, api=_BoomApi(), call_sid="CA1"
    )
    data = json.loads(result)
    assert "menu" in data["voice_fallback"].lower()


@pytest.mark.asyncio
async def test_take_message_uses_take_message_specific_fallback():
    """If take_message itself fails, the fallback can't be 'want me to take
    a message?' — that's a loop. Use a different phrasing."""
    result = await handle_tool_call(
        "take_message",
        {"callback_number": "+15551234567", "reason": "catering"},
        api=_BoomApi(),
        call_sid="CA1",
    )
    data = json.loads(result)
    assert "message" in data["voice_fallback"].lower() or "later" in data["voice_fallback"].lower()
    # Must NOT loop into "take a message" again
    assert "take a message" not in data["voice_fallback"].lower()


@pytest.mark.asyncio
async def test_unknown_tool_still_errors_cleanly():
    """Unknown tool name continues to return a JSON error (existing behavior)."""
    result = await handle_tool_call(
        "no_such_tool", {}, api=_BoomApi(), call_sid="CA1"
    )
    data = json.loads(result)
    assert "error" in data


@pytest.mark.asyncio
async def test_send_order_link_without_phone_doesnt_call_api():
    """Existing pre-check stays: missing from_phone short-circuits to
    'ask for number, use take_message'. Voice fallback NOT triggered
    (this isn't an error, it's a guard)."""
    result = await handle_tool_call(
        "send_order_link", {}, api=_BoomApi(), call_sid="CA1", from_phone=""
    )
    data = json.loads(result)
    assert "error" in data
    # No voice_fallback because we didn't call the API
    assert "voice_fallback" not in data
