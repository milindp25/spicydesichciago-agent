"""Stub FirebaseAuthVerifier for integration tests.

The real verifier calls firebase_admin.auth.verify_id_token which needs
the default app initialized + a real signed JWT. Tests use this stub
which decodes a JSON-encoded fake token and applies the same allowlist
logic.

Fake token format: "fake:<email>" — e.g. "fake:techtastellc@gmail.com".
"""
from __future__ import annotations

from app.api.middleware.firebase_auth import AuthError


class StubFirebaseAuthVerifier:
    def __init__(self, *, allowed_emails: list[str]) -> None:
        self._allowlist = {e.lower().strip() for e in allowed_emails if e.strip()}

    def verify(self, token: str) -> dict[str, object]:
        if not token:
            raise AuthError("missing")
        if not token.startswith("fake:"):
            raise AuthError(f"invalid token: not a fake: prefix ({token[:10]}...)")
        email = token[len("fake:"):].lower()
        if email not in self._allowlist:
            raise AuthError(f"{email} not in admin allowlist")
        return {
            "uid": f"uid-{email.split('@')[0]}",
            "email": email,
            "email_verified": True,
        }
