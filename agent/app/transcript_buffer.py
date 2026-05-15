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
