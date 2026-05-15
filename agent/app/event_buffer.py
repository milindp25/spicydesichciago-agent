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
