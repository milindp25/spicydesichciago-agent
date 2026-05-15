from __future__ import annotations

import base64
import time

import pytest

from app.services.callback_tokens import decode, encode

SECRET = "k" * 32


def test_roundtrip_preserves_payload() -> None:
    tok = encode(
        {"message_id": "m1", "caller_phone": "+13125551111", "owner_phone": "+15555550199"},
        secret=SECRET,
        ttl_seconds=60,
    )
    out = decode(tok, secret=SECRET)
    assert out["message_id"] == "m1"
    assert out["caller_phone"] == "+13125551111"
    assert out["owner_phone"] == "+15555550199"
    assert isinstance(out["exp"], int)
    assert out["exp"] >= int(time.time())


def test_expired_token_raises() -> None:
    tok = encode({"x": 1}, secret=SECRET, ttl_seconds=1)
    # Decode at a time well past expiry.
    with pytest.raises(ValueError, match="expired"):
        decode(tok, secret=SECRET, now_unix=int(time.time()) + 3600)


def test_bad_signature_raises() -> None:
    tok = encode({"x": 1}, secret=SECRET, ttl_seconds=60)
    with pytest.raises(ValueError, match="bad signature"):
        decode(tok, secret="different-secret")


def test_tampered_payload_raises() -> None:
    tok = encode({"x": 1, "caller_phone": "+1111"}, secret=SECRET, ttl_seconds=60)
    payload_b64, sig_b64 = tok.split(".")
    # Tamper: substitute a different (valid) base64 payload.
    other_raw = b'{"x":2,"exp":9999999999,"caller_phone":"+2222"}'
    other_b64 = base64.urlsafe_b64encode(other_raw).rstrip(b"=").decode("ascii")
    tampered = f"{other_b64}.{sig_b64}"
    with pytest.raises(ValueError, match="bad signature"):
        decode(tampered, secret=SECRET)


def test_malformed_token_raises() -> None:
    with pytest.raises(ValueError):
        decode("not-a-token", secret=SECRET)


def test_empty_secret_raises() -> None:
    with pytest.raises(ValueError):
        encode({"x": 1}, secret="", ttl_seconds=60)
    with pytest.raises(ValueError):
        decode("a.b", secret="", now_unix=0)
