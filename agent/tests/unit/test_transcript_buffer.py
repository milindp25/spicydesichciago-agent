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
