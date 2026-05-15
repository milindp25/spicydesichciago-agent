# Agent Call-Lifecycle Adoption + LLM End-of-Call Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the agent to call `/api/calls/{sid}/start` at call begin, `/api/calls/{sid}/end` at hangup, and `/api/calls/{sid}/summary` after generating a one-line LLM summary of the conversation — so the dashboard sees rich per-call data instead of just appended events.

**Architecture:** Three new POST routes on the API service write to `FirestoreCallStore` (already exists). The agent's `bot.py` registers a Pipecat frame observer that buffers user + assistant utterances. On WebSocket close, the agent runs a single Groq completion against the buffered transcript to produce a 1-sentence summary, then posts start/end/summary in sequence. Existing `/api/calls/{sid}/event` route stays as-is for fine-grained event capture.

**Tech Stack:** FastAPI, Pipecat 1.1 frame observer pattern, Groq (existing client), Firestore (existing stores from Plan 2a).

**Branch:** `feature/agent-adoption-summary` from `feature/firestore-persistence`.

**Depends on:** Plan 2a (Firestore persistence) — `FirestoreCallStore.record_call_start/end/set_summary` already exist and are tested.

**Out of scope (separate plans):**
- Voice fallback lines on tool errors — Plan 3
- Reliable event retry queue — Plan 3
- Dashboard auth — Plan 4

---

## Pre-flight context

- Baseline branch: `feature/firestore-persistence` (43 commits ahead of main, 113 API tests, 66 agent tests passing).
- Existing `FirestoreCallStore` methods we'll wire to: `record_call_start(call: Call)`, `record_call_end(call_sid, ended_at, outcome, duration_ms)`, `set_summary(call_sid, summary)`, `append_event(call_sid, event, caller_phone_for_upsert, from_number_for_upsert)`.
- Existing agent → API client at `agent/app/tools/api_client.py` already has `append_event`. We extend it.
- Existing system prompt: `agent/app/prompts/system.md` — no changes needed in this plan.
- Existing Pipecat pipeline: `agent/app/bot.py` `run_bot(ws, settings, stream_sid, call_sid, from_phone)` — adds observer + lifecycle hooks here.
- Groq LLM client is already configured in `bot.py` (used for the main conversation). We reuse the same client for summary generation.

---

## File structure

```
api/
  app/
    api/
      routes/
        calls.py          ← NEW: POST /start, /end, /summary
    domain/
      call.py             ← reused (Plan 2a)
  tests/
    integration/
      test_calls_route.py ← NEW

agent/
  app/
    summary.py            ← NEW: prompt + Groq call for LLM summary
    transcript_buffer.py  ← NEW: thread-safe buffer for user/assistant frames
    bot.py                ← MODIFIED: wire observer + lifecycle hooks
    tools/
      api_client.py       ← MODIFIED: add record_call_start/end/summary
  tests/
    unit/
      test_transcript_buffer.py    ← NEW
      test_summary.py              ← NEW
      test_api_client_lifecycle.py ← NEW (extends existing test_api_client)
```

---

## Phase 1 — API: call-lifecycle routes

### Task 1.1: Add three POST routes (TDD)

**Files:**
- Create: `api/app/api/routes/calls.py`
- Create: `api/tests/integration/test_calls_route.py`
- Modify: `api/app/api/app_factory.py` (include the new router)

- [ ] **Step 1: Write failing integration tests**

Create `api/tests/integration/test_calls_route.py`:

```python
"""Integration tests for /api/calls/{sid}/{start,end,summary}."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.call import Outcome


@pytest.mark.asyncio
async def test_start_creates_call_doc(client_factory, firestore_db, secret):
    state, client = client_factory(firestore_db=firestore_db)
    started_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc).isoformat()

    resp = client.post(
        "/api/calls/CA-test-1/start",
        json={
            "started_at": started_at,
            "caller_phone": "+15551234567",
            "from_number": "+15559998888",
        },
        headers={"X-Tools-Auth": secret},
    )
    assert resp.status_code == 202
    assert resp.json() == {"ok": True}

    call = state.call_store.get_call("CA-test-1")
    assert call is not None
    assert call.caller_phone == "+15551234567"
    assert call.from_number == "+15559998888"
    assert call.outcome == Outcome.IN_PROGRESS


@pytest.mark.asyncio
async def test_end_sets_outcome_duration(client_factory, firestore_db, secret):
    state, client = client_factory(firestore_db=firestore_db)
    started = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=94)

    client.post(
        "/api/calls/CA-test-2/start",
        json={
            "started_at": started.isoformat(),
            "caller_phone": "+15551234567",
            "from_number": "+15559998888",
        },
        headers={"X-Tools-Auth": secret},
    )
    resp = client.post(
        "/api/calls/CA-test-2/end",
        json={
            "ended_at": ended.isoformat(),
            "outcome": "resolved",
            "duration_ms": 94000,
        },
        headers={"X-Tools-Auth": secret},
    )
    assert resp.status_code == 202
    call = state.call_store.get_call("CA-test-2")
    assert call is not None
    assert call.outcome == Outcome.RESOLVED
    assert call.duration_ms == 94000


@pytest.mark.asyncio
async def test_summary_sets_summary(client_factory, firestore_db, secret):
    state, client = client_factory(firestore_db=firestore_db)
    started = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    client.post(
        "/api/calls/CA-test-3/start",
        json={
            "started_at": started.isoformat(),
            "caller_phone": "+15551234567",
            "from_number": "+15559998888",
        },
        headers={"X-Tools-Auth": secret},
    )
    resp = client.post(
        "/api/calls/CA-test-3/summary",
        json={"summary": "Asked about hours and momos; sent order link"},
        headers={"X-Tools-Auth": secret},
    )
    assert resp.status_code == 202
    call = state.call_store.get_call("CA-test-3")
    assert call is not None
    assert call.summary == "Asked about hours and momos; sent order link"


@pytest.mark.asyncio
async def test_end_without_start_creates_call_via_upsert(
    client_factory, firestore_db, secret,
):
    """If hangup arrives without prior start (network blip), don't 404 —
    create the parent doc with the supplied end-time data and mark the
    call's startedAt = endedAt as a best effort."""
    state, client = client_factory(firestore_db=firestore_db)
    ended = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)

    resp = client.post(
        "/api/calls/CA-orphan/end",
        json={
            "ended_at": ended.isoformat(),
            "outcome": "failed",
            "duration_ms": 0,
            "caller_phone": "+15551234567",
            "from_number": "+15559998888",
        },
        headers={"X-Tools-Auth": secret},
    )
    assert resp.status_code == 202
    call = state.call_store.get_call("CA-orphan")
    assert call is not None
    assert call.outcome == Outcome.FAILED
```

- [ ] **Step 2: Run tests, confirm failure**

```bash
(cd api && .venv/bin/pytest tests/integration/test_calls_route.py -v 2>&1 | tail -20)
```
Expected: import errors / 404s because the route doesn't exist yet.

- [ ] **Step 3: Implement the route**

Create `api/app/api/routes/calls.py`:

```python
"""POST /api/calls/{sid}/start, /end, /summary — call lifecycle endpoints
used by the agent. Writes to FirestoreCallStore.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.dependencies import get_state, require_tools_auth
from app.domain.call import Call, Outcome

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


class StartBody(BaseModel):
    started_at: datetime
    caller_phone: str
    from_number: str


class EndBody(BaseModel):
    ended_at: datetime
    outcome: Outcome
    duration_ms: int = Field(0, ge=0)
    # Optional upsert fields when /end arrives without a prior /start
    caller_phone: str = ""
    from_number: str = ""


class SummaryBody(BaseModel):
    summary: str


@router.post("/calls/{call_sid}/start", status_code=202)
async def call_start(request: Request, call_sid: str, body: StartBody) -> dict[str, Any]:
    state = get_state(request)
    state.call_store.record_call_start(
        Call(
            call_sid=call_sid,
            started_at=body.started_at,
            caller_phone=body.caller_phone,
            from_number=body.from_number,
        )
    )
    return {"ok": True}


@router.post("/calls/{call_sid}/end", status_code=202)
async def call_end(request: Request, call_sid: str, body: EndBody) -> dict[str, Any]:
    state = get_state(request)
    # Upsert parent doc if /start was never received
    existing = state.call_store.get_call(call_sid)
    if existing is None:
        state.call_store.record_call_start(
            Call(
                call_sid=call_sid,
                started_at=body.ended_at,  # best-effort: collapse start = end
                caller_phone=body.caller_phone or "+0",
                from_number=body.from_number or "+0",
            )
        )
    state.call_store.record_call_end(
        call_sid=call_sid,
        ended_at=body.ended_at,
        outcome=body.outcome,
        duration_ms=body.duration_ms,
    )
    return {"ok": True}


@router.post("/calls/{call_sid}/summary", status_code=202)
async def call_summary(request: Request, call_sid: str, body: SummaryBody) -> dict[str, Any]:
    state = get_state(request)
    state.call_store.set_summary(call_sid=call_sid, summary=body.summary)
    return {"ok": True}
```

- [ ] **Step 4: Register the router**

Edit `api/app/api/app_factory.py`. Add import alongside other route imports:

```python
from app.api.routes import (
    address,
    callers,
    calls,           # NEW
    events,
    health,
    ...
)
```

And in the `build_app(deps)` function, add `app.include_router(calls.router)` alongside the other `app.include_router(...)` calls.

- [ ] **Step 5: Run integration tests**

```bash
(cd api && .venv/bin/pytest tests/integration/test_calls_route.py -v 2>&1 | tail -20)
```
Expected: 4 passed.

- [ ] **Step 6: Run full API suite**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 117 passed (113 + 4 new).

- [ ] **Step 7: Commit**

```bash
git add api/app/api/routes/calls.py api/app/api/app_factory.py \
        api/tests/integration/test_calls_route.py
git commit -m "feat(api): POST /api/calls/{sid}/{start,end,summary} routes

Wires FirestoreCallStore.record_call_start/end/set_summary as REST
endpoints. /end is forgiving — upserts a parent doc if /start was
never received (network glitch on the agent side)."
```

---

## Phase 2 — Agent: transcript buffer + summary generator

### Task 2.1: TranscriptBuffer (TDD)

**Files:**
- Create: `agent/app/transcript_buffer.py`
- Create: `agent/tests/unit/test_transcript_buffer.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/unit/test_transcript_buffer.py`:

```python
"""Tests for TranscriptBuffer (used by bot to capture utterances for summary)."""
from __future__ import annotations

from app.transcript_buffer import TranscriptBuffer


def test_starts_empty():
    buf = TranscriptBuffer()
    assert buf.as_text() == ""
    assert len(buf) == 0


def test_appends_user_and_assistant_turns():
    buf = TranscriptBuffer()
    buf.add_user("what time do you open?")
    buf.add_assistant("we open at 11am")
    assert len(buf) == 2
    text = buf.as_text()
    assert "caller: what time do you open?" in text.lower()
    assert "agent: we open at 11am" in text.lower()


def test_truncates_long_input():
    """Each utterance is capped at 500 chars so a 30-minute call doesn't
    blow context limits for the summary LLM call."""
    buf = TranscriptBuffer()
    buf.add_user("a" * 2000)
    text = buf.as_text()
    user_line = next(line for line in text.split("\n") if line.lower().startswith("caller:"))
    # Body is capped + has an ellipsis indicator
    assert len(user_line) <= 520
    assert "..." in user_line


def test_caps_total_turns():
    """Only the last N turns are kept — keeps summary input bounded for
    very long calls."""
    buf = TranscriptBuffer(max_turns=4)
    buf.add_user("u1")
    buf.add_assistant("a1")
    buf.add_user("u2")
    buf.add_assistant("a2")
    buf.add_user("u3")
    assert len(buf) == 4
    text = buf.as_text()
    assert "u1" not in text
    assert "u3" in text


def test_ignores_empty_strings():
    buf = TranscriptBuffer()
    buf.add_user("")
    buf.add_user("   ")
    buf.add_assistant(None)  # type: ignore[arg-type]
    assert len(buf) == 0


def test_thread_safe_append():
    """Concurrent appends from Pipecat frame observers must not corrupt
    the deque or interleave fields. Smoke test: 100 quick appends."""
    import threading

    buf = TranscriptBuffer(max_turns=200)

    def add_many(n: int) -> None:
        for i in range(n):
            buf.add_user(f"u{i}")
            buf.add_assistant(f"a{i}")

    threads = [threading.Thread(target=add_many, args=(50,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 4 threads * 50 user + 50 assistant = 400 appends; max_turns caps at 200
    assert len(buf) == 200
    # Buffer didn't crash — that's the win
```

- [ ] **Step 2: Run tests, confirm failure**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_transcript_buffer.py -v 2>&1 | tail -15)
```
Expected: `ModuleNotFoundError: No module named 'app.transcript_buffer'`.

- [ ] **Step 3: Implement**

Create `agent/app/transcript_buffer.py`:

```python
"""TranscriptBuffer — capture caller and agent utterances for the
end-of-call summary LLM call. Thread-safe via a lock; bounded so a
30-minute call doesn't blow context limits.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass


MAX_UTTERANCE_CHARS = 500
DEFAULT_MAX_TURNS = 80  # ~40 user + 40 agent turns; covers a typical call


@dataclass(frozen=True)
class _Turn:
    role: str  # "caller" or "agent"
    text: str


class TranscriptBuffer:
    def __init__(self, *, max_turns: int = DEFAULT_MAX_TURNS) -> None:
        self._turns: deque[_Turn] = deque(maxlen=max_turns)
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._turns)

    def add_user(self, text: str | None) -> None:
        self._add("caller", text)

    def add_assistant(self, text: str | None) -> None:
        self._add("agent", text)

    def _add(self, role: str, text: str | None) -> None:
        if not text or not text.strip():
            return
        body = text.strip()
        if len(body) > MAX_UTTERANCE_CHARS:
            body = body[:MAX_UTTERANCE_CHARS] + "..."
        with self._lock:
            self._turns.append(_Turn(role=role, text=body))

    def as_text(self) -> str:
        with self._lock:
            return "\n".join(f"{t.role}: {t.text}" for t in self._turns)
```

- [ ] **Step 4: Run tests**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_transcript_buffer.py -v 2>&1 | tail -15)
```
Expected: 6 passed.

- [ ] **Step 5: Full agent suite**

```bash
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 72 passed (66 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add agent/app/transcript_buffer.py agent/tests/unit/test_transcript_buffer.py
git commit -m "feat(agent): TranscriptBuffer for end-of-call summary input

Thread-safe deque; caps utterances at 500 chars and total turns at 80
so a 30-min call doesn't blow LLM context."
```

### Task 2.2: SummaryGenerator (TDD)

**Files:**
- Create: `agent/app/summary.py`
- Create: `agent/tests/unit/test_summary.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/unit/test_summary.py`:

```python
"""Tests for SummaryGenerator (LLM-driven 1-sentence call summary)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.summary import SummaryGenerator, build_summary_prompt
from app.transcript_buffer import TranscriptBuffer


def test_prompt_includes_transcript():
    buf = TranscriptBuffer()
    buf.add_user("what time do you open?")
    buf.add_assistant("we open at 11am")
    prompt = build_summary_prompt(buf.as_text())
    assert "caller: what time" in prompt.lower()
    assert "agent: we open" in prompt.lower()
    # Prompt should constrain the LLM to a single sentence
    assert "one sentence" in prompt.lower() or "single sentence" in prompt.lower()


def test_prompt_handles_empty_transcript():
    """If the buffer is empty (call dropped before any speech), the prompt
    should still produce a deterministic short string, not crash."""
    prompt = build_summary_prompt("")
    assert prompt  # non-empty string
    assert "empty" in prompt.lower() or "no transcript" in prompt.lower()


@pytest.mark.asyncio
async def test_generate_calls_llm_and_returns_summary():
    """SummaryGenerator wraps a Groq client. Mock the client; verify the
    HTTP shape (model, messages, max_tokens) and that the response content
    is returned verbatim (after strip + truncation)."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Asked about hours; got the answer."))]
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    gen = SummaryGenerator(llm_client=mock_client, model="llama-3.3-70b-versatile")
    buf = TranscriptBuffer()
    buf.add_user("what time do you open?")
    buf.add_assistant("we open at 11am")

    summary = await gen.generate(buf.as_text())
    assert summary == "Asked about hours; got the answer."

    # Verify the call shape
    call_args = mock_client.chat.completions.create.await_args
    assert call_args.kwargs["model"] == "llama-3.3-70b-versatile"
    assert call_args.kwargs["max_tokens"] <= 80
    messages = call_args.kwargs["messages"]
    assert any("caller: what time" in m["content"].lower() for m in messages)


@pytest.mark.asyncio
async def test_generate_returns_empty_when_llm_fails():
    """If Groq is down or returns garbage, return empty string — caller
    can decide to leave summary unset rather than crash the hangup path."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("groq down"))

    gen = SummaryGenerator(llm_client=mock_client, model="llama-3.3-70b-versatile")
    summary = await gen.generate("caller: hi\nagent: hi")
    assert summary == ""


@pytest.mark.asyncio
async def test_generate_truncates_long_response():
    """Defense vs LLM ignoring 'one sentence' constraint — cap final
    output at 300 chars."""
    long_text = "x" * 1000
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=long_text))]
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    gen = SummaryGenerator(llm_client=mock_client, model="llama-3.3-70b-versatile")
    summary = await gen.generate("caller: hi")
    assert len(summary) <= 300
    assert summary.endswith("...")
```

- [ ] **Step 2: Run tests, confirm failure**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_summary.py -v 2>&1 | tail -10)
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `agent/app/summary.py`:

```python
"""SummaryGenerator — LLM-driven 1-sentence call summary.

Uses the same chat-completions client the main bot uses (Groq or any
OpenAI-compatible endpoint). The prompt strongly constrains the model
to a single sentence; we additionally cap output at 300 chars in case
the model ignores the constraint.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol


log = logging.getLogger(__name__)

MAX_SUMMARY_CHARS = 300


def build_summary_prompt(transcript_text: str) -> str:
    if not transcript_text.strip():
        return (
            "The conversation transcript is empty (call dropped before any "
            "speech). Return the single word: dropped."
        )
    return (
        "You are summarizing a phone call between a restaurant's AI assistant "
        "and a customer. Write ONE sentence (max 25 words) describing what "
        "the caller asked about and whether they got an answer. Use past "
        "tense. Do not use quotes or bullet points. Do not name the "
        "restaurant.\n\n"
        f"Transcript:\n{transcript_text}\n\n"
        "Summary (one sentence):"
    )


class _ChatClient(Protocol):
    chat: Any  # has .completions.create(...)


class SummaryGenerator:
    def __init__(self, *, llm_client: _ChatClient, model: str) -> None:
        self._client = llm_client
        self._model = model

    async def generate(self, transcript_text: str) -> str:
        prompt = build_summary_prompt(transcript_text)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "You are a concise summarizer."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=80,
                temperature=0.2,
            )
            content = (response.choices[0].message.content or "").strip()
        except Exception:
            log.exception("summary generation failed")
            return ""

        if len(content) > MAX_SUMMARY_CHARS:
            content = content[: MAX_SUMMARY_CHARS - 3] + "..."
        return content
```

- [ ] **Step 4: Run tests**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_summary.py -v 2>&1 | tail -15)
```
Expected: 5 passed.

- [ ] **Step 5: Full agent suite**

```bash
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 77 passed (72 + 5 new).

- [ ] **Step 6: Commit**

```bash
git add agent/app/summary.py agent/tests/unit/test_summary.py
git commit -m "feat(agent): SummaryGenerator with single-sentence prompt + length cap

Reuses the same chat-completions client as the main bot. Empty transcript
returns 'dropped'. Failures from the LLM provider return empty string —
caller decides whether to skip the summary write."
```

---

## Phase 3 — Agent: lifecycle methods on ApiClient (TDD)

### Task 3.1: Extend ApiClient with start/end/summary

**Files:**
- Modify: `agent/app/tools/api_client.py`
- Modify: `agent/tests/unit/test_api_client.py`

- [ ] **Step 1: Append failing tests to the existing api_client test file**

Open `agent/tests/unit/test_api_client.py` and append:

```python
import pytest
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_record_call_start_posts_to_start_route(api_client_with_mock):
    client, mock = api_client_with_mock
    await client.record_call_start(
        call_sid="CA1",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    request = mock.calls[-1].request
    assert request.url.path == "/api/calls/CA1/start"
    assert request.method == "POST"
    import json
    body = json.loads(request.content)
    assert body["caller_phone"] == "+15551234567"
    assert body["from_number"] == "+15559998888"
    assert body["started_at"].startswith("2026-05-14T12:00:00")


@pytest.mark.asyncio
async def test_record_call_end_posts_end_route(api_client_with_mock):
    client, mock = api_client_with_mock
    await client.record_call_end(
        call_sid="CA1",
        ended_at=datetime(2026, 5, 14, 12, 1, 30, tzinfo=timezone.utc),
        outcome="resolved",
        duration_ms=90000,
    )
    request = mock.calls[-1].request
    assert request.url.path == "/api/calls/CA1/end"
    import json
    body = json.loads(request.content)
    assert body["outcome"] == "resolved"
    assert body["duration_ms"] == 90000


@pytest.mark.asyncio
async def test_record_call_summary_posts_summary_route(api_client_with_mock):
    client, mock = api_client_with_mock
    await client.record_call_summary(
        call_sid="CA1",
        summary="Asked about hours and momos; sent order link",
    )
    request = mock.calls[-1].request
    assert request.url.path == "/api/calls/CA1/summary"
    import json
    body = json.loads(request.content)
    assert body["summary"] == "Asked about hours and momos; sent order link"


@pytest.mark.asyncio
async def test_lifecycle_methods_swallow_http_errors(api_client_with_failing_mock):
    """If the API is down, lifecycle calls must not raise — they're best-effort.
    The transcript should be optional and never block hangup."""
    client, _ = api_client_with_failing_mock
    # None of these should raise even though the API returns 500
    await client.record_call_start(
        call_sid="CA1",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    await client.record_call_end(
        call_sid="CA1",
        ended_at=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
        outcome="failed",
        duration_ms=60000,
    )
    await client.record_call_summary(call_sid="CA1", summary="test")
```

You'll need two new fixtures. Look at the existing `api_client_with_mock` fixture in the test file (likely uses `httpx.MockTransport`). Add a sibling fixture `api_client_with_failing_mock` that returns 500 for every request. Concrete shape:

```python
@pytest.fixture
def api_client_with_failing_mock():
    """API client backed by a transport that returns 500 for every request."""
    import httpx
    from app.tools.api_client import ApiClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    mock = httpx.MockTransport(handler)
    client = ApiClient(
        base_url="http://test",
        secret="x" * 32,
        tenant="spicy-desi",
        transport=mock,
    )
    yield client, mock
```

If `api_client_with_mock` doesn't already exist, build it the same way but with a handler that returns `httpx.Response(202, json={"ok": True})` and stores the request for later inspection. Look at the existing test file's fixture pattern and reuse it; the existing tests already POST to `/api/calls/{sid}/event` so the fixture exists in some form.

- [ ] **Step 2: Run tests, confirm failure**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_api_client.py -v -k "record_call" 2>&1 | tail -20)
```
Expected: 4 failures — `AttributeError: 'ApiClient' object has no attribute 'record_call_start'`.

- [ ] **Step 3: Implement the methods**

In `agent/app/tools/api_client.py`, add these methods to the `ApiClient` class (before `aclose`):

```python
    async def record_call_start(
        self,
        *,
        call_sid: str,
        started_at: "datetime",
        caller_phone: str,
        from_number: str,
    ) -> None:
        """Best-effort POST to /api/calls/{sid}/start. Swallows HTTP errors."""
        try:
            await self._client.post(
                f"/api/calls/{call_sid}/start",
                json={
                    "started_at": started_at.isoformat(),
                    "caller_phone": caller_phone,
                    "from_number": from_number,
                },
            )
        except Exception:
            log.exception("record_call_start failed", extra={"call_sid": call_sid})

    async def record_call_end(
        self,
        *,
        call_sid: str,
        ended_at: "datetime",
        outcome: str,
        duration_ms: int,
        caller_phone: str = "",
        from_number: str = "",
    ) -> None:
        try:
            await self._client.post(
                f"/api/calls/{call_sid}/end",
                json={
                    "ended_at": ended_at.isoformat(),
                    "outcome": outcome,
                    "duration_ms": duration_ms,
                    "caller_phone": caller_phone,
                    "from_number": from_number,
                },
            )
        except Exception:
            log.exception("record_call_end failed", extra={"call_sid": call_sid})

    async def record_call_summary(self, *, call_sid: str, summary: str) -> None:
        try:
            await self._client.post(
                f"/api/calls/{call_sid}/summary",
                json={"summary": summary},
            )
        except Exception:
            log.exception("record_call_summary failed", extra={"call_sid": call_sid})
```

Add at the top of the file (if not already present):

```python
import logging
from datetime import datetime  # noqa: F401 — used in type hints below

log = logging.getLogger(__name__)
```

Note: the lifecycle methods deliberately do NOT call `raise_for_status()`. They're best-effort because they run on call hangup and must never block the WebSocket close. Errors are logged.

This is different from the rest of `ApiClient` (which DOES raise) — those are called during the conversation, so failure is recoverable by surfacing to the model. Lifecycle calls have no recovery path; logging is enough.

- [ ] **Step 4: Run tests**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_api_client.py -v -k "record_call" 2>&1 | tail -20)
```
Expected: 4 passed.

- [ ] **Step 5: Full agent suite**

```bash
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 81 passed (77 + 4 new).

- [ ] **Step 6: Commit**

```bash
git add agent/app/tools/api_client.py agent/tests/unit/test_api_client.py
git commit -m "feat(agent): ApiClient.record_call_{start,end,summary} (best-effort)

Lifecycle calls swallow HTTP errors and log — they run on hangup and
must never block the WebSocket close. Different contract from the
in-conversation methods which raise (and let the model recover)."
```

---

## Phase 4 — Wire into bot.py

### Task 4.1: Attach TranscriptBuffer to Pipecat pipeline

**Files:**
- Modify: `agent/app/bot.py`

- [ ] **Step 1: Read the current bot.py**

```bash
cat agent/app/bot.py
```
Note where the Pipecat pipeline is constructed. Look for `from pipecat.frames.frames import ...` and where frames flow through the pipeline.

- [ ] **Step 2: Add the observer + lifecycle hooks**

You're adding three pieces inside `run_bot`:

(a) **Construct a `TranscriptBuffer`** immediately when run_bot starts.

(b) **Register a frame observer** that:
- Appends `TranscriptionFrame` text to `buf.add_user(...)`
- Appends `TTSTextFrame` (or `LLMTextFrame`) text to `buf.add_assistant(...)`

In Pipecat 1.1 the way to attach an observer is via `pipeline.events.on(...)` for frame events, or by injecting a `FrameProcessor` subclass into the pipeline. The minimum-invasive approach: create a small `FrameProcessor` subclass that taps frames and forwards them unchanged.

Add this helper class inside `bot.py` near the top (or in a new module if you prefer):

```python
from pipecat.frames.frames import Frame, LLMTextFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class _TranscriptTap(FrameProcessor):
    """Frame processor that snoops user transcripts + assistant LLM text
    into a TranscriptBuffer without modifying the frame stream."""
    def __init__(self, buf: "TranscriptBuffer") -> None:
        super().__init__()
        self._buf = buf

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            self._buf.add_user(getattr(frame, "text", None))
        elif isinstance(frame, LLMTextFrame):
            self._buf.add_assistant(getattr(frame, "text", None))
        await self.push_frame(frame, direction)
```

Then insert an instance of `_TranscriptTap(transcript_buffer)` into the Pipeline construction — placement matters; typically place it right after the STT and right after the LLM in the pipeline so it sees user transcripts and assistant output cleanly.

Concretely: when `bot.py` builds `pipeline = Pipeline([transport.input(), stt, ...the rest..., transport.output()])`, insert `_TranscriptTap(transcript_buffer)` once after `stt` and once after the LLM. The frame types are different at those points, so the same tap class handles both.

(c) **In `run_bot`, after the pipeline finishes (caller hangs up or timeout fires)**, call lifecycle methods on the API client:

```python
    # ... pipeline.run finishes here ...

    from datetime import datetime, timezone
    ended_at = datetime.now(timezone.utc)
    duration_ms = int((ended_at - started_at).total_seconds() * 1000) if started_at else 0
    outcome = "resolved"  # default; refined below

    # If the call ended because of the 90s cap, outcome is "transferred"
    # (the 90s handler already triggers a transfer). bot.py needs to track
    # how the call ended; the simplest signal is whether the OwnerShortcut
    # or timeout fired. For this iteration, default to "resolved" and let
    # subsequent work refine outcome detection.

    await api_client.record_call_end(
        call_sid=call_sid,
        ended_at=ended_at,
        outcome=outcome,
        duration_ms=duration_ms,
        caller_phone=from_phone,
        from_number="",  # to-number is on the Twilio side; not in stream params today
    )

    # Generate + post summary (best-effort, ~200 tokens on Groq)
    if len(transcript_buffer) > 0:
        summary = await summary_generator.generate(transcript_buffer.as_text())
        if summary:
            await api_client.record_call_summary(call_sid=call_sid, summary=summary)
```

The exact `outcome` detection is rough on this pass — refine in Plan 3 once we have better signal (e.g., owner-transfer event triggers `transferred`, take-message event triggers `messageTaken`).

(d) **Add a `record_call_start` call at the top of `run_bot`**, right after the WebSocket `start` event is received:

```python
    started_at = datetime.now(timezone.utc)
    await api_client.record_call_start(
        call_sid=call_sid,
        started_at=started_at,
        caller_phone=from_phone or "+0",
        from_number="",  # see note in record_call_end above
    )
```

The exact placement depends on where `api_client` is constructed in run_bot. If it's built inside run_bot from `settings`, place `record_call_start` immediately after construction. If it's passed in from `server.py`, just call it at the top of run_bot.

(e) **Construct the `SummaryGenerator`** alongside the api_client. It needs the same Groq client the main pipeline uses. Look for where the LLM service is constructed in `bot.py` (something like `OpenAILLMService(...)` or `GroqLLMService(...)`). If the client is exposed via `.client` or similar attribute, pass that to `SummaryGenerator`. If not, build a parallel `AsyncOpenAI` or `AsyncGroq` client using the same env values.

**Important constraint:** the summary call is allowed to fail silently. The agent must hang up cleanly even if Groq is unreachable. Already covered by `SummaryGenerator.generate` returning "" on exception.

- [ ] **Step 3: Run agent tests to confirm nothing regressed**

```bash
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 81 passed. If `tests/integration/test_server_routes.py` or similar breaks because they import `bot.py` and the import-time pipecat dependency tree changed, that's a real concern — the plan's helper class uses pipecat imports at module level. Solution: wrap the pipecat imports inside `_TranscriptTap.__init__` or `process_frame` so module-level import still works. The bot.py module is documented as "Pipecat is imported lazily so module-level import succeeds without the heavy voice stack" — preserve that.

If you can't preserve lazy import, the tests that depend on it will fail. Move `_TranscriptTap` to a separate module that's imported lazily inside `run_bot`.

- [ ] **Step 4: Commit**

```bash
git add agent/app/bot.py
git commit -m "feat(agent): wire call lifecycle (start/end/summary) + transcript tap

Pipecat FrameProcessor (_TranscriptTap) snoops TranscriptionFrame and
LLMTextFrame into a TranscriptBuffer without modifying the stream.
On hangup: posts /end + (if transcript non-empty) /summary. Lifecycle
posts are best-effort (errors logged, not raised) so a flaky API
never blocks the WebSocket close."
```

---

## Phase 5 — End-to-end sanity check (local)

### Task 5.1: Wire docker-compose env + run smoke

**Files:** None (compose already has Firebase env from Plan 2a)

- [ ] **Step 1: Confirm the test suites are green**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: API 117 passed, agent 81 passed.

- [ ] **Step 2: Build and boot via docker compose** (only if Docker is running; skip otherwise)

```bash
# Build .env.local from the two .env files (same pattern as Plan 2a verification)
{
  grep -E "^[A-Z_]+=" agent/.env
  grep -E "^[A-Z_]+=" api/.env
} | awk -F= '!seen[$1]++' > .env.local
sed -i.bak 's|^TOOLS_API_BASE=.*|TOOLS_API_BASE=http://api:8080|' .env.local && rm .env.local.bak
echo "FIREBASE_SERVICE_ACCOUNT_HOST_PATH=$HOME/.config/spicy-desi/firebase-admin.json" >> .env.local

docker compose --env-file .env.local up -d --build
sleep 12
curl -fsS http://localhost:8080/healthz
curl -fsS http://localhost:8090/healthz
docker compose --env-file .env.local down
rm .env.local
```
Expected: both `{"ok":true}`. The agent isn't exercised here (no Twilio call) but boot confirms imports + wiring are clean.

If you have a way to simulate a Twilio inbound call locally (Twilio CLI, ngrok), do an end-to-end test: dial → exchange a few utterances → hang up → check Firestore for `/calls/CA-test/start*`, `/calls/CA-test/end*`, `/calls/CA-test/summary`. Otherwise defer this to post-deploy verification.

### Task 5.2: Push the branch

```bash
git push -u origin feature/agent-adoption-summary 2>&1 | tail -5
```

Capture the PR URL. PR can be opened once Plan 2a lands on main.

---

## Verification

End-to-end:
1. `(cd api && .venv/bin/pytest tests/ -q)` → 117 passed (113 baseline + 4 new lifecycle route tests).
2. `(cd agent && .venv/bin/pytest tests/ -q)` → 81 passed (66 baseline + 6 buffer + 5 summary + 4 api client = 81).
3. Local boot: both `/healthz` endpoints respond `{"ok":true}` under docker-compose.
4. Real call (post-deploy): dial Twilio → after hangup, dashboard subscribed to `/calls/{sid}` sees `startedAt`, `endedAt`, `durationMs`, `outcome`, `summary` populated, plus per-call events in `/calls/{sid}/events/` subcollection.

---

## What's next (separate plans)

- **Plan 3**: Voice fallback lines on tool errors + reliable event retry queue (roadmap 0.1, 0.2). Refines outcome detection by tracking the last significant event before hangup.
- **Plan 4**: Dashboard API + Firebase Auth verification + rate limiting.
