"""Firebase Auth ID token verification + email allowlist.

Used by the dashboard-facing /api/admin/* routes. The agent service
uses X-Tools-Auth shared-secret and never touches this module.

Production behavior:
- Browser sends Authorization: Bearer <firebase-id-token> on every
  request to /api/admin/*.
- firebase_admin.auth.verify_id_token() validates the JWT signature,
  expiration, audience, etc.
- We additionally require email_verified=True and email-in-allowlist.

Misconfiguration safety: empty allowlist rejects EVERY token. Set
ADMIN_ALLOWED_EMAILS to the owner emails before going live.
"""
from __future__ import annotations

from typing import Any

from firebase_admin import auth as firebase_auth


class AuthError(Exception):
    """Raised when a token is missing, invalid, or the email isn't allowed."""


class FirebaseAuthVerifier:
    def __init__(self, *, allowed_emails: list[str]) -> None:
        # Lowercase for case-insensitive match
        self._allowlist = {e.lower().strip() for e in allowed_emails if e.strip()}

    def verify(self, token: str) -> dict[str, Any]:
        if not token:
            raise AuthError("missing Authorization Bearer token")

        try:
            decoded = firebase_auth.verify_id_token(token)
        except Exception as e:
            # firebase_admin raises various subclasses (InvalidIdTokenError,
            # ExpiredIdTokenError, RevokedIdTokenError, CertificateFetchError).
            # All map to 401 — invalid token.
            raise AuthError(f"invalid token: {type(e).__name__}") from e

        email = (decoded.get("email") or "").lower()
        if not decoded.get("email_verified", False):
            raise AuthError("email not verified")
        if email not in self._allowlist:
            raise AuthError(f"{email} not in admin allowlist")
        return decoded
