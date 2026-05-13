"""Validate inbound Twilio webhooks via X-Twilio-Signature."""
from __future__ import annotations

from twilio.request_validator import RequestValidator


class TwilioSignatureVerifier:
    """
    Wraps Twilio's RequestValidator with a dev-mode bypass.

    When auth_token is empty (typical in local development without Twilio
    credentials), verification is DISABLED and verify() accepts any request.
    Production must set TWILIO_AUTH_TOKEN — otherwise the bypass leaves the
    Twilio webhook endpoints open to forged requests.
    """

    def __init__(self, auth_token: str) -> None:
        self._validator = RequestValidator(auth_token) if auth_token else None

    def is_enabled(self) -> bool:
        return self._validator is not None

    def verify(
        self,
        *,
        url: str,
        form: dict[str, str],
        signature: str | None,
    ) -> bool:
        if self._validator is None:
            return True
        if not signature:
            return False
        return self._validator.validate(url, form, signature)
