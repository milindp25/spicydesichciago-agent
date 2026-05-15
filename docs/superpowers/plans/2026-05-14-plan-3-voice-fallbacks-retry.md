# Voice Fallbacks + Reliable Event Retry + Enhanced Transfer SMS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the voice agent resilient to API outages: (1) tool handlers return a structured `voice_fallback` string when an API call fails, which the LLM speaks instead of going silent; (2) `record_event` calls go through a retry queue with backoff and local-disk fallback so events aren't lost on transient API blips; (3) when a take-message comes in, the SMS to the owner includes richer caller context (timestamp, call_sid, click-to-call link).

**Architecture:** A new `agent/app/tools/handler_result.py` wraps tool-call execution in a try/except that emits `{"error": "...", "voice_fallback": "..."}` JSON the LLM understands. A new `agent/app/event_buffer.py` provides an `asyncio.Queue`-backed retry queue (3 attempts with exponential backoff, then writes to `/tmp/spicy-desi-failed-events.jsonl` for manual reconciliation). The `/api/messages` route gains a `to_phone` formatter that produces a richer SMS body and uses `tel:` deep-link in the click-back text.

**Tech Stack:** Python 3.12, FastAPI, httpx (existing), asyncio, no new deps.

**Branch:** `feature/voice-fallbacks-retry` from main (or layered on top of 2a/2b once those land).

**Depends on:** Plan 2a (Firestore persistence). Plan 2b is optional — these changes are agent-side and don't require call lifecycle routes.

**Out of scope (separate plans):**
- Agent adoption of call-lifecycle routes — Plan 2b
- Dashboard API + auth — Plan 4
- Daily SMS digest — roadmap 0.5, deferred (dashboard real-time view covers it)

---

## Pre-flight context

- Existing `agent/app/tools/handlers.py` is a flat if/elif dispatcher. We wrap dispatch in error handling, not rewrite it.
- Existing `agent/app/tools/api_client.py` has `append_event(call_sid, kind, payload)` — fire-and-forget but without retry. We replace this call site with the new queue.
- Existing system prompt at `agent/app/prompts/system.md` — we add a single rule about handling tool errors.
- Tool errors today: `api.get_pickup_today()` raises `httpx.HTTPError` on timeout (default 10s); the agent goes silent for ~10s, model retries the same tool, often loops. Voice UX is bad.
- `/api/messages` route already sends an SMS to the owner. Body is currently `"Spicy Desi AI message — <name> (<phone>): <reason>"`. We add timestamp + click-back link.

---

## File structure

```
agent/
  app/
    tools/
      handlers.py              ← MODIFY: wrap calls in try/except + structured error
      handler_result.py        ← NEW: error → voice_fallback shape
      api_client.py            ← MODIFY: replace append_event direct POST with queue.put
    event_buffer.py            ← NEW: asyncio.Queue + retry worker + JSONL fallback
    bot.py                     ← MODIFY: construct EventBuffer + start its worker
    prompts/
      system.md                ← MODIFY: add error-fallback rule
  tests/
    unit/
      test_handler_result.py   ← NEW
      test_event_buffer.py     ← NEW
      test_handlers_errors.py  ← NEW (extends existing handlers tests)

api/
  app/
    api/
      routes/
        messages.py            ← MODIFY: enrich SMS body
  tests/
    integration/
      test_messages_route.py   ← MODIFY: assert new SMS body shape
```

---

## Phase 1 — Voice fallback for tool errors

### Task 1.1: HandlerResult helper (TDD)

**Files:**
- Create: `agent/app/tools/handler_result.py`
- Create: `agent/tests/unit/test_handler_result.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/unit/test_handler_result.py`:

```python
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
```

- [ ] **Step 2: Run tests, confirm failure**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_handler_result.py -v 2>&1 | tail -15)
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `agent/app/tools/handler_result.py`:

```python
"""Error wrapper for tool handlers — turns Python exceptions into a
JSON payload the LLM speaks instead of going silent.

The contract with the system prompt: when a tool returns a payload
with both `error` and `voice_fallback` keys, the model should say
the voice_fallback string verbatim (or a close paraphrase) and offer
to take a message. The prompt's rule for this is in system.md.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

import httpx

log = logging.getLogger(__name__)


DEFAULT_VOICE_FALLBACK = (
    "Hmm, looks like I can't pull that up right now. "
    "Want me to take a message and we'll call you back?"
)


def error_payload(error: str, *, voice_fallback: str | None = None) -> str:
    """Serialize an error+fallback into the JSON shape tool handlers
    return on failure."""
    return json.dumps(
        {
            "error": error,
            "voice_fallback": voice_fallback or DEFAULT_VOICE_FALLBACK,
        }
    )


async def safe_call(
    fn: Callable[[], Awaitable[Any]],
    *,
    voice_fallback: str | None = None,
) -> str:
    """Run fn() and JSON-serialize its return value. On any exception,
    log it and return error_payload(...) instead. Always returns a string
    safe to pass back to the LLM as a tool result."""
    try:
        result = await fn()
        return json.dumps(result)
    except httpx.TimeoutException as e:
        log.warning("tool call timeout", extra={"detail": str(e)})
        return error_payload(f"API timeout: {e}", voice_fallback=voice_fallback)
    except httpx.HTTPError as e:
        log.warning("tool call HTTP error", extra={"detail": str(e)})
        return error_payload(f"API error: {e}", voice_fallback=voice_fallback)
    except Exception as e:
        log.exception("tool call unexpected error")
        return error_payload(f"unexpected: {type(e).__name__}", voice_fallback=voice_fallback)
```

- [ ] **Step 4: Run tests**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_handler_result.py -v 2>&1 | tail -10)
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/tools/handler_result.py agent/tests/unit/test_handler_result.py
git commit -m "feat(agent): handler_result.safe_call wraps tool errors in voice_fallback

Voice fallback string is what the model says instead of going silent
when an API call fails. Tool-specific fallbacks override the default
('want me to take a message?')."
```

### Task 1.2: Wrap each handler in safe_call + per-tool fallbacks

**Files:**
- Modify: `agent/app/tools/handlers.py`
- Create: `agent/tests/unit/test_handlers_errors.py`

- [ ] **Step 1: Write failing tests for error handling**

Create `agent/tests/unit/test_handlers_errors.py`:

```python
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
```

- [ ] **Step 2: Run tests, confirm failure**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_handlers_errors.py -v 2>&1 | tail -15)
```
Expected: 4 failures (the BoomApi raises, but handlers don't catch yet).

- [ ] **Step 3: Refactor handlers.py to use safe_call**

Replace `agent/app/tools/handlers.py` with:

```python
from __future__ import annotations

import json
from typing import Any

from app.tools.api_client import ApiClient
from app.tools.handler_result import error_payload, safe_call


# Tool-specific voice fallbacks. The default ("can't pull that up,
# want me to take a message?") is fine for most tools, but a few need
# tighter phrasing — especially take_message itself, which would loop
# if it offered to take a message on failure.
_FALLBACKS: dict[str, str] = {
    "search_menu": (
        "I'm having trouble pulling up the menu just now. "
        "Want me to take a message and we'll call you back with details?"
    ),
    "list_menu_categories": (
        "I'm having trouble pulling up the menu just now. "
        "Want me to take a message and we'll call you back with details?"
    ),
    "list_full_menu": (
        "I'm having trouble pulling up the menu just now. "
        "Want me to take a message and we'll call you back with details?"
    ),
    "get_specials": (
        "Hmm, our specials aren't loading — give us a call back in a few minutes "
        "or I can take a message."
    ),
    "take_message": (
        "I couldn't write that down on our end, sorry. "
        "Please try again in a moment, or call back later."
    ),
    "request_transfer": (
        "I can't reach the owner right now. "
        "Want me to grab a message instead and they'll call you back?"
    ),
    "send_order_link": (
        "I couldn't send that link via text just now. "
        "Want me to take a message instead?"
    ),
    "send_location_link": (
        "I couldn't send the location via text just now. "
        "I can describe how to get here, or take a message."
    ),
}


async def handle_tool_call(
    name: str,
    args: dict[str, Any],
    *,
    api: ApiClient,
    call_sid: str,
    from_phone: str = "",
) -> str:
    fallback = _FALLBACKS.get(name)

    if name == "get_pickup_today":
        return await safe_call(api.get_pickup_today, voice_fallback=fallback)
    if name == "search_menu":
        query = args.get("query", "")
        return await safe_call(lambda: api.search_menu(query), voice_fallback=fallback)
    if name == "list_full_menu":
        category = args.get("category")
        return await safe_call(lambda: api.list_full_menu(category=category), voice_fallback=fallback)
    if name == "list_menu_categories":
        return await safe_call(api.list_menu_categories, voice_fallback=fallback)
    if name == "get_specials":
        return await safe_call(api.get_specials, voice_fallback=fallback)

    if name == "send_order_link":
        # Pre-check: no phone → short-circuit (NOT an error, no fallback)
        if not from_phone:
            return json.dumps(
                {"error": "no caller phone; ask for their number and use take_message"}
            )
        return await safe_call(
            lambda: api.send_sms_link(call_sid=call_sid, to=from_phone, kind="order"),
            voice_fallback=fallback,
        )
    if name == "send_location_link":
        if not from_phone:
            return json.dumps({"error": "no caller phone; ask for their number"})
        return await safe_call(
            lambda: api.send_sms_link(call_sid=call_sid, to=from_phone, kind="location"),
            voice_fallback=fallback,
        )

    if name == "take_message":
        return await safe_call(
            lambda: api.take_message(
                call_sid=call_sid,
                callback_number=args["callback_number"],
                reason=args["reason"],
                caller_name=args.get("caller_name"),
            ),
            voice_fallback=fallback,
        )
    if name == "request_transfer":
        return await safe_call(
            lambda: api.request_transfer(call_sid=call_sid, reason=args.get("reason")),
            voice_fallback=fallback,
        )
    return error_payload(f"unknown tool: {name}")
```

- [ ] **Step 4: Run new error tests + existing handler tests**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_handlers_errors.py tests/unit/test_handlers.py -v 2>&1 | tail -25)
```
Expected: new 5 tests pass; existing handler tests STILL pass (some may need updates if they asserted on raw response shape — adjust by checking for `error` key absent on success path).

If existing tests broke because they asserted `json.loads(result)["x"]` and the result is now wrapped differently, fix by reading: the new handlers wrap the same success payload via `safe_call` which returns `json.dumps(result)` — IDENTICAL to before on success. They should not have broken. If they did, capture the diff and revert any unintended shape change.

- [ ] **Step 5: Full agent suite**

```bash
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 71 passed (66 baseline + 5 new — the existing handlers tests count is unchanged since shape is preserved on success).

- [ ] **Step 6: Commit**

```bash
git add agent/app/tools/handlers.py agent/tests/unit/test_handlers_errors.py
git commit -m "feat(agent): wrap every tool handler in safe_call with per-tool fallbacks

Tool errors no longer cause the bot to go silent. Each tool has a
hand-written fallback line; take_message + request_transfer fallbacks
deliberately avoid 'want me to take a message?' loops."
```

### Task 1.3: Teach the system prompt to use voice_fallback

**Files:**
- Modify: `agent/app/prompts/system.md`

- [ ] **Step 1: Add a rule near existing error-handling guidance**

Read the current prompt:
```bash
cat agent/app/prompts/system.md
```

Add this rule under the "Hard rules" or equivalent section (preserve all existing content; just insert):

```markdown
## Tool errors

When a tool returns a JSON payload with both `error` and `voice_fallback` keys, that means the API call failed. You MUST:
1. Read the `voice_fallback` text aloud verbatim (or a close paraphrase that keeps the same intent).
2. Do NOT retry the same tool immediately — the failure is likely persistent for several seconds.
3. After speaking the fallback, wait for the caller to respond. If they accept (take a message, call back later), proceed with that flow. If they ask the same question, you may try the tool once more.

Never say "the API failed" or "error" to the caller. Use the voice_fallback exactly because it's been written for them.
```

- [ ] **Step 2: Verify prompt still loads**

```bash
(cd agent && .venv/bin/python -c "
from app.bot import load_system_prompt
text = load_system_prompt()
print(f'Length: {len(text)} chars')
assert 'voice_fallback' in text.lower()
print('OK')
")
```
Expected: prints `OK`.

- [ ] **Step 3: Commit**

```bash
git add agent/app/prompts/system.md
git commit -m "feat(agent): system prompt teaches model to speak voice_fallback on tool error

Rules: (1) speak voice_fallback verbatim, (2) don't retry the same
tool immediately, (3) never say 'API failed' to the caller."
```

---

## Phase 2 — Reliable event retry queue

### Task 2.1: EventBuffer (TDD)

**Files:**
- Create: `agent/app/event_buffer.py`
- Create: `agent/tests/unit/test_event_buffer.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/unit/test_event_buffer.py`:

```python
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
```

- [ ] **Step 2: Run tests, confirm failure**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_event_buffer.py -v 2>&1 | tail -15)
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement EventBuffer**

Create `agent/app/event_buffer.py`:

```python
"""EventBuffer — asyncio.Queue-backed retry queue for event POSTs.

Design:
- `put()` enqueues an event; returns immediately.
- A background worker drains the queue, calling `post_fn(call_sid, kind, payload)`.
- On any exception, retry up to `max_attempts` with exponential backoff.
- After max_attempts, write the event to a JSONL fallback file for manual
  reconciliation. The API has a backfill script (Plan 2a Task 6.1) that can
  replay these.
- `stop()` flushes pending events before returning, so hangup-time events
  don't get dropped.
- `put()` after `stop()` writes directly to the fallback file.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)


class EventBuffer:
    def __init__(
        self,
        *,
        post_fn: Callable[[str, str, dict[str, Any]], Awaitable[None]],
        fallback_path: Path,
        max_attempts: int = 3,
        backoff_base_seconds: float = 0.5,
    ) -> None:
        self._post = post_fn
        self._fallback_path = fallback_path
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds
        self._queue: asyncio.Queue[tuple[str, str, dict[str, Any]]] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._stopped = False

    async def start(self) -> None:
        if self._worker_task is not None:
            return
        self._worker_task = asyncio.create_task(self._run(), name="event-buffer-worker")

    async def stop(self) -> None:
        """Wait for the queue to drain, then cancel the worker."""
        await self._queue.join()
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        self._stopped = True

    async def put(self, *, call_sid: str, kind: str, payload: dict[str, Any]) -> None:
        if self._stopped:
            self._write_fallback(call_sid, kind, payload, reason="put-after-stop")
            return
        await self._queue.put((call_sid, kind, payload))

    async def _run(self) -> None:
        while True:
            call_sid, kind, payload = await self._queue.get()
            try:
                await self._post_with_retry(call_sid, kind, payload)
            finally:
                self._queue.task_done()

    async def _post_with_retry(
        self, call_sid: str, kind: str, payload: dict[str, Any]
    ) -> None:
        for attempt in range(1, self._max_attempts + 1):
            try:
                await self._post(call_sid, kind, payload)
                return
            except Exception as e:
                if attempt == self._max_attempts:
                    log.warning(
                        "event post failed after retries",
                        extra={
                            "call_sid": call_sid,
                            "kind": kind,
                            "attempts": attempt,
                            "error": str(e),
                        },
                    )
                    self._write_fallback(call_sid, kind, payload, reason=f"max_attempts: {e}")
                    return
                wait = self._backoff_base * (2 ** (attempt - 1))
                await asyncio.sleep(wait)

    def _write_fallback(
        self,
        call_sid: str,
        kind: str,
        payload: dict[str, Any],
        *,
        reason: str,
    ) -> None:
        record = {
            "call_sid": call_sid,
            "kind": kind,
            "payload": payload,
            "ts": time.time(),
            "fallback_reason": reason,
        }
        try:
            self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
            with self._fallback_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
        except Exception:
            log.exception(
                "failed to write event fallback file",
                extra={"path": str(self._fallback_path)},
            )
```

- [ ] **Step 4: Run tests**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_event_buffer.py -v 2>&1 | tail -15)
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/event_buffer.py agent/tests/unit/test_event_buffer.py
git commit -m "feat(agent): EventBuffer — asyncio.Queue + retry + JSONL fallback

3 attempts with exponential backoff; failures land in a JSONL file the
backfill script can replay. stop() drains pending events before
returning, so hangup-time events don't get lost."
```

### Task 2.2: Wire EventBuffer into bot.py + replace direct api_client.append_event

**Files:**
- Modify: `agent/app/bot.py`
- Modify: `agent/app/tools/api_client.py` (just the docstring; we don't change append_event itself)

- [ ] **Step 1: Construct EventBuffer in run_bot**

In `agent/app/bot.py`, inside `run_bot(...)` after the existing api_client construction, add:

```python
    from pathlib import Path
    from app.event_buffer import EventBuffer

    event_buffer = EventBuffer(
        post_fn=lambda call_sid, kind, payload: api_client.append_event(
            call_sid=call_sid, kind=kind, payload=payload
        ),
        fallback_path=Path("/tmp/spicy-desi-failed-events.jsonl"),
    )
    await event_buffer.start()
```

The lambda binds `api_client.append_event` to the EventBuffer's `post_fn` shape.

At the END of run_bot (before WebSocket close, after pipeline.run finishes), add:

```python
    await event_buffer.stop()  # flush pending events
```

- [ ] **Step 2: Replace direct calls to api_client.append_event in bot.py**

Find every `await api_client.append_event(...)` in bot.py and replace with `await event_buffer.put(...)`. The signature is identical (same kwargs). This routes events through the retry queue.

The agent's existing event writes (in the conversation loop, e.g. when a tool succeeds and we log a "tool_called" event) all flow through the buffer now.

- [ ] **Step 3: Verify agent tests still pass**

```bash
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 71 passed. The tests don't exercise the buffer in run_bot; they test it in isolation. Any test that mocks the pipeline shouldn't break — but if `test_bot_module.py` or similar imports bot.py and checks shape, ensure imports stay clean.

- [ ] **Step 4: Commit**

```bash
git add agent/app/bot.py
git commit -m "feat(agent): route call events through EventBuffer (retry + JSONL fallback)

All in-conversation event writes now go through the retry queue.
Buffer is drained on hangup before the WebSocket closes."
```

---

## Phase 3 — Enhanced transfer-failure SMS to owner

### Task 3.1: Richer SMS body with timestamp + click-to-call link

**Files:**
- Modify: `api/app/api/routes/messages.py`
- Modify: `api/tests/integration/test_messages_route.py`

- [ ] **Step 1: Update the test to assert the new SMS body shape**

Open `api/tests/integration/test_messages_route.py`. Find the test that asserts the SMS body. Update the expected substring assertions to look for:
- The caller phone in the body
- The reason in the body
- A `tel:` deep link (or `click to call:` text with the phone in tel-URI form)
- An approximate timestamp marker (e.g. "received at" or date string)

Example update to whatever existing SMS assertions look like:

```python
# Before:
# assert "(+15551234567)" in twilio_stub.sent_messages[0]["body"]

# After:
body = twilio_stub.sent_messages[0]["body"]
assert "+15551234567" in body
assert "catering" in body
assert "tel:+15551234567" in body or "click to call" in body.lower()
# Timestamp marker — match either ISO date or "received" wording
assert any(token in body.lower() for token in ["received", "2026-05"])
```

- [ ] **Step 2: Run tests, confirm failure**

```bash
(cd api && .venv/bin/pytest tests/integration/test_messages_route.py -v 2>&1 | tail -20)
```
Expected: SMS body assertion failures.

- [ ] **Step 3: Update the route's SMS body formatter**

In `api/app/api/routes/messages.py`, find the line:
```python
    sms_body = (
        f"Spicy Desi AI message — {body.caller_name or 'unknown'} "
        f"({body.callback_number}): {body.reason}"
    )
```

Replace with a richer body:
```python
    from datetime import datetime

    received = datetime.now().strftime("%-I:%M %p")  # e.g., "3:42 PM" (zero-stripped hour)
    caller_label = body.caller_name or "unknown caller"
    sms_body = (
        f"Spicy Desi voice agent — message at {received}\n"
        f"{caller_label} ({body.callback_number}): {body.reason}\n"
        f"Call back: tel:{body.callback_number}"
    )
```

The `tel:` URI lets iOS / Android Messages auto-detect it as a tap-to-call link in the SMS.

- [ ] **Step 4: Run tests**

```bash
(cd api && .venv/bin/pytest tests/integration/test_messages_route.py -v 2>&1 | tail -15)
```
Expected: all pass.

- [ ] **Step 5: Full API suite**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 113 passed (no count change; we modified an existing test).

- [ ] **Step 6: Commit**

```bash
git add api/app/api/routes/messages.py api/tests/integration/test_messages_route.py
git commit -m "feat(api): richer take-message SMS to owner (timestamp + tap-to-call)

Body now includes time-of-day and a tel: URI so iMessage / SMS clients
render a tap-to-call link. Caller name still shown when supplied."
```

---

## Phase 4 — Sanity + push

### Task 4.1: Full regression + push branch

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: API 113 passed, agent 76 passed (66 baseline + 6 handler_result + 5 handlers_errors — count adjusts based on what landed exactly).

Push:
```bash
git push -u origin feature/voice-fallbacks-retry 2>&1 | tail -5
```

---

## Verification

End-to-end (assumes Plan 2a is on the branch):
1. Tool error simulated locally: stop the API; agent should speak the fallback line instead of going silent.
2. Event buffer: kill the API briefly during a call; events should land in `/tmp/spicy-desi-failed-events.jsonl`; restart API and re-run the backfill script (Plan 2a Task 6.1) on that fallback file to recover them.
3. Take-message SMS: owner receives an SMS with timestamp, caller info, reason, and a tap-to-call link.

---

## What's next (separate plans)

- **Plan 4**: Dashboard API + Firebase Auth + rate limiting. The owner will use the dashboard to mark messages as handled, set/clear availability override, view today's calls inline.
- **Optional follow-up**: refine `outcome` detection in bot.py — track whether the call ended via take-message, transfer-completed, or natural hangup, and pass the precise outcome to `record_call_end`. Today's default is "resolved" which is imprecise.
