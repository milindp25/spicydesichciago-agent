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
