"""Tests for handler_result — error-to-voice-fallback wrapper for tool handlers."""
from __future__ import annotations

import json

import httpx
import pytest

from app.tools.handler_result import (
    error_payload,
    safe_call,
)


def test_error_payload_includes_voice_fallback():
    """Returns a JSON string the LLM can interpret as 'tell the user we
    failed, then offer to take a message'."""
    payload = error_payload("API timeout")
    data = json.loads(payload)
    assert data["error"] == "API timeout"
    assert "voice_fallback" in data
    # The voice fallback should be a complete sentence
    assert len(data["voice_fallback"]) > 10
    assert data["voice_fallback"].endswith((".", "?", "!"))


def test_error_payload_uses_default_voice_fallback_when_msg_short():
    payload = error_payload("boom")
    data = json.loads(payload)
    # The error string can be technical; voice_fallback must be customer-friendly
    assert "boom" not in data["voice_fallback"].lower()


@pytest.mark.asyncio
async def test_safe_call_passes_through_success():
    async def ok() -> dict[str, int]:
        return {"answer": 42}

    result = await safe_call(ok)
    assert json.loads(result) == {"answer": 42}


@pytest.mark.asyncio
async def test_safe_call_catches_httpx_errors():
    """Network errors -> structured fallback, not a raise."""
    async def boom() -> None:
        raise httpx.TimeoutException("read timeout")

    result = await safe_call(boom)
    data = json.loads(result)
    assert "error" in data
    assert "voice_fallback" in data
    assert "timeout" in data["error"].lower()


@pytest.mark.asyncio
async def test_safe_call_catches_generic_exceptions():
    """Programmer errors also go through the fallback path so the bot
    doesn't go silent on an unexpected exception."""
    async def boom() -> None:
        raise ValueError("bad arg")

    result = await safe_call(boom)
    data = json.loads(result)
    assert "error" in data
    assert "voice_fallback" in data


@pytest.mark.asyncio
async def test_safe_call_custom_fallback_used():
    """Caller can supply a tool-specific voice fallback (e.g., 'I couldn't
    pull the menu right now' rather than the generic one)."""
    async def boom() -> None:
        raise RuntimeError("boom")

    result = await safe_call(
        boom,
        voice_fallback="I couldn't pull up the menu right now — want me to take a message?",
    )
    data = json.loads(result)
    assert "menu" in data["voice_fallback"].lower()
