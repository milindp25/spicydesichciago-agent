"""Tests for TwilioSignatureVerifier."""
from __future__ import annotations

import pytest
from twilio.request_validator import RequestValidator

from app.security.twilio_signature import TwilioSignatureVerifier


AUTH_TOKEN = "test-auth-token-32-bytes-long-xx"
URL = "https://agent.spicydesichicago.com/twilio/inbound"
FORM = {"From": "+15551234567", "CallSid": "CA123"}


def _make_signature(token: str, url: str, form: dict[str, str]) -> str:
    return RequestValidator(token).compute_signature(url, form)


def test_accepts_valid_signature() -> None:
    verifier = TwilioSignatureVerifier(auth_token=AUTH_TOKEN)
    sig = _make_signature(AUTH_TOKEN, URL, FORM)
    assert verifier.verify(url=URL, form=FORM, signature=sig) is True


def test_rejects_missing_signature() -> None:
    verifier = TwilioSignatureVerifier(auth_token=AUTH_TOKEN)
    assert verifier.verify(url=URL, form=FORM, signature="") is False
    assert verifier.verify(url=URL, form=FORM, signature=None) is False


def test_rejects_tampered_signature() -> None:
    verifier = TwilioSignatureVerifier(auth_token=AUTH_TOKEN)
    sig = _make_signature(AUTH_TOKEN, URL, FORM)
    tampered = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    assert verifier.verify(url=URL, form=FORM, signature=tampered) is False


def test_rejects_signature_with_wrong_token() -> None:
    verifier = TwilioSignatureVerifier(auth_token=AUTH_TOKEN)
    sig = _make_signature("different-token-32-bytes-long-yy", URL, FORM)
    assert verifier.verify(url=URL, form=FORM, signature=sig) is False


def test_rejects_signature_with_modified_form() -> None:
    verifier = TwilioSignatureVerifier(auth_token=AUTH_TOKEN)
    sig = _make_signature(AUTH_TOKEN, URL, FORM)
    modified = {**FORM, "From": "+15559999999"}
    assert verifier.verify(url=URL, form=modified, signature=sig) is False


def test_empty_auth_token_disables_verification() -> None:
    """If TWILIO_AUTH_TOKEN is unset (empty), verifier is in dev mode and accepts all."""
    verifier = TwilioSignatureVerifier(auth_token="")
    assert verifier.verify(url=URL, form=FORM, signature="anything") is True
    assert verifier.is_enabled() is False


def test_enabled_when_token_present() -> None:
    verifier = TwilioSignatureVerifier(auth_token=AUTH_TOKEN)
    assert verifier.is_enabled() is True


def test_build_app_warns_in_dev_when_token_missing(caplog: pytest.LogCaptureFixture) -> None:
    """Dev mode without token should log a warning, not raise."""
    import logging
    from app.config import AgentSettings
    from app.server import build_app

    settings = AgentSettings(
        TOOLS_API_BASE="http://test",
        TOOLS_SHARED_SECRET="x" * 32,
        GROQ_API_KEY="test",
        DEEPGRAM_API_KEY="test",
        CARTESIA_API_KEY="test",
        CARTESIA_VOICE_ID="test-voice",
        TWILIO_AUTH_TOKEN="",
        APP_ENV="development",
    )
    with caplog.at_level(logging.WARNING):
        build_app(settings)
    assert any("DISABLED" in r.message for r in caplog.records)


def test_build_app_refuses_to_boot_in_production_without_token() -> None:
    """Production without TWILIO_AUTH_TOKEN must raise to prevent silent-bypass deploy."""
    from app.config import AgentSettings
    from app.server import build_app

    settings = AgentSettings(
        TOOLS_API_BASE="http://test",
        TOOLS_SHARED_SECRET="x" * 32,
        GROQ_API_KEY="test",
        DEEPGRAM_API_KEY="test",
        CARTESIA_API_KEY="test",
        CARTESIA_VOICE_ID="test-voice",
        TWILIO_AUTH_TOKEN="",
        APP_ENV="production",
    )
    with pytest.raises(RuntimeError, match="TWILIO_AUTH_TOKEN is required in production"):
        build_app(settings)
