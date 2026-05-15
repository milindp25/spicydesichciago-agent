from __future__ import annotations

import pytest

from app.config import AgentSettings


_REQUIRED = dict(
    TOOLS_API_BASE="http://test",
    TOOLS_SHARED_SECRET="x" * 32,
    GROQ_API_KEY="test",
    DEEPGRAM_API_KEY="test",
    CARTESIA_API_KEY="test",
    CARTESIA_VOICE_ID="test-voice",
)


def test_vad_defaults() -> None:
    s = AgentSettings(**_REQUIRED)
    assert s.vad_stop_secs == 0.6
    assert s.vad_start_secs == 0.2


def test_vad_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_VAD_STOP_SECS", "0.8")
    monkeypatch.setenv("AGENT_VAD_START_SECS", "0.15")
    s = AgentSettings(**_REQUIRED)
    assert s.vad_stop_secs == 0.8
    assert s.vad_start_secs == 0.15
