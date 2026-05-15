"""Tests for EventBuffer — retry queue for /api/calls/{sid}/event posts."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.event_buffer import EventBuffer


@pytest.fixture
def tmp_fallback_path(tmp_path: Path) -> Path:
    return tmp_path / "failed-events.jsonl"


@pytest.mark.asyncio
async def test_successful_post_drains_queue(tmp_fallback_path):
    posts_seen = []

    async def post(call_sid: str, kind: str, payload: dict) -> None:
        posts_seen.append((call_sid, kind, payload))

    buf = EventBuffer(post_fn=post, fallback_path=tmp_fallback_path, max_attempts=3)
    await buf.start()
    try:
        await buf.put(call_sid="CA1", kind="toolCalled", payload={"tool": "x"})
        await asyncio.sleep(0.1)  # let worker run
    finally:
        await buf.stop()

    assert posts_seen == [("CA1", "toolCalled", {"tool": "x"})]
    assert not tmp_fallback_path.exists()


@pytest.mark.asyncio
async def test_retries_on_failure_then_writes_to_fallback(tmp_fallback_path):
    attempts = 0

    async def flaky_post(call_sid: str, kind: str, payload: dict) -> None:
        nonlocal attempts
        attempts += 1
        raise httpx.HTTPError("nope")

    buf = EventBuffer(
        post_fn=flaky_post,
        fallback_path=tmp_fallback_path,
        max_attempts=3,
        backoff_base_seconds=0.01,  # fast for tests
    )
    await buf.start()
    try:
        await buf.put(call_sid="CA1", kind="toolCalled", payload={"tool": "x"})
        await asyncio.sleep(0.5)
    finally:
        await buf.stop()

    assert attempts == 3  # initial + 2 retries
    assert tmp_fallback_path.exists()
    content = tmp_fallback_path.read_text().strip()
    record = json.loads(content)
    assert record["call_sid"] == "CA1"
    assert record["kind"] == "toolCalled"
    assert record["payload"] == {"tool": "x"}


@pytest.mark.asyncio
async def test_success_after_one_failure_no_fallback(tmp_fallback_path):
    attempts = 0

    async def eventually_works(call_sid: str, kind: str, payload: dict) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise httpx.HTTPError("transient")

    buf = EventBuffer(
        post_fn=eventually_works,
        fallback_path=tmp_fallback_path,
        max_attempts=3,
        backoff_base_seconds=0.01,
    )
    await buf.start()
    try:
        await buf.put(call_sid="CA1", kind="toolCalled", payload={})
        await asyncio.sleep(0.3)
    finally:
        await buf.stop()

    assert attempts == 2
    assert not tmp_fallback_path.exists()


@pytest.mark.asyncio
async def test_stop_drains_pending_queue(tmp_fallback_path):
    posts_seen = []

    async def post(call_sid: str, kind: str, payload: dict) -> None:
        posts_seen.append((call_sid, kind, payload))

    buf = EventBuffer(post_fn=post, fallback_path=tmp_fallback_path, max_attempts=3)
    await buf.start()
    for i in range(5):
        await buf.put(call_sid="CA1", kind=f"k{i}", payload={"i": i})
    await buf.stop()  # must process all 5 before returning

    assert len(posts_seen) == 5


@pytest.mark.asyncio
async def test_put_after_stop_writes_directly_to_fallback(tmp_fallback_path):
    """If something tries to put after the buffer is stopped (e.g.,
    last-second event during hangup), don't lose the event — write
    directly to the fallback file."""
    async def post(call_sid: str, kind: str, payload: dict) -> None:
        pass

    buf = EventBuffer(post_fn=post, fallback_path=tmp_fallback_path, max_attempts=3)
    await buf.start()
    await buf.stop()
    await buf.put(call_sid="CA1", kind="late", payload={"x": 1})

    assert tmp_fallback_path.exists()
    record = json.loads(tmp_fallback_path.read_text().strip())
    assert record["kind"] == "late"
