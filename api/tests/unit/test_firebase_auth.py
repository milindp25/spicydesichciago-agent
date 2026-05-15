"""Tests for FirebaseAuthVerifier (token verification + email allowlist)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.api.middleware.firebase_auth import (
    AuthError,
    FirebaseAuthVerifier,
)


def test_verify_returns_uid_email_on_valid_token():
    """Mock verify_id_token to return a known decoded payload."""
    decoded = {"uid": "uid-owner", "email": "techtastellc@gmail.com", "email_verified": True}
    with patch(
        "app.api.middleware.firebase_auth.firebase_auth.verify_id_token",
        return_value=decoded,
    ):
        verifier = FirebaseAuthVerifier(allowed_emails=["techtastellc@gmail.com"])
        result = verifier.verify("any-token-string")
    assert result["uid"] == "uid-owner"
    assert result["email"] == "techtastellc@gmail.com"


def test_verify_rejects_missing_token():
    verifier = FirebaseAuthVerifier(allowed_emails=["techtastellc@gmail.com"])
    with pytest.raises(AuthError) as exc:
        verifier.verify("")
    assert "missing" in str(exc.value).lower()


def test_verify_rejects_invalid_token():
    from firebase_admin.auth import InvalidIdTokenError
    with patch(
        "app.api.middleware.firebase_auth.firebase_auth.verify_id_token",
        side_effect=InvalidIdTokenError("bad token"),
    ):
        verifier = FirebaseAuthVerifier(allowed_emails=["techtastellc@gmail.com"])
        with pytest.raises(AuthError) as exc:
            verifier.verify("garbage")
    assert "invalid" in str(exc.value).lower()


def test_verify_rejects_email_not_in_allowlist():
    decoded = {"uid": "uid-stranger", "email": "stranger@example.com", "email_verified": True}
    with patch(
        "app.api.middleware.firebase_auth.firebase_auth.verify_id_token",
        return_value=decoded,
    ):
        verifier = FirebaseAuthVerifier(allowed_emails=["techtastellc@gmail.com"])
        with pytest.raises(AuthError) as exc:
            verifier.verify("token")
    assert "not authorized" in str(exc.value).lower() or "allowlist" in str(exc.value).lower()


def test_verify_rejects_unverified_email():
    """Firebase Auth supports unverified emails. We require verified."""
    decoded = {"uid": "uid", "email": "techtastellc@gmail.com", "email_verified": False}
    with patch(
        "app.api.middleware.firebase_auth.firebase_auth.verify_id_token",
        return_value=decoded,
    ):
        verifier = FirebaseAuthVerifier(allowed_emails=["techtastellc@gmail.com"])
        with pytest.raises(AuthError):
            verifier.verify("token")


def test_email_match_is_case_insensitive():
    decoded = {"uid": "uid", "email": "TechTasteLLC@Gmail.com", "email_verified": True}
    with patch(
        "app.api.middleware.firebase_auth.firebase_auth.verify_id_token",
        return_value=decoded,
    ):
        verifier = FirebaseAuthVerifier(allowed_emails=["techtastellc@gmail.com"])
        result = verifier.verify("token")
    assert result["email"].lower() == "techtastellc@gmail.com"


def test_empty_allowlist_rejects_everyone():
    """Defense against misconfiguration — never allow any user when
    allowlist is empty."""
    decoded = {"uid": "uid", "email": "techtastellc@gmail.com", "email_verified": True}
    with patch(
        "app.api.middleware.firebase_auth.firebase_auth.verify_id_token",
        return_value=decoded,
    ):
        verifier = FirebaseAuthVerifier(allowed_emails=[])
        with pytest.raises(AuthError):
            verifier.verify("token")
