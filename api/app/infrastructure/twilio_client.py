from __future__ import annotations

import logging
from typing import Protocol

from twilio.rest import Client as TwilioRestClient

log = logging.getLogger(__name__)


class TwilioOps(Protocol):
    async def send_sms(self, *, to: str, body: str) -> bool: ...
    async def redirect_call(self, *, call_sid: str, twiml_url: str) -> bool: ...
    async def create_call(self, *, to: str, from_: str, url: str) -> str | None: ...


class RealTwilioClient:
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self._client = TwilioRestClient(account_sid, auth_token) if account_sid else None
        self._from = from_number

    async def send_sms(self, *, to: str, body: str) -> bool:
        if self._client is None or not self._from:
            log.warning("twilio not configured; skipping send_sms", extra={"to": to})
            return False
        try:
            self._client.messages.create(to=to, from_=self._from, body=body)
            return True
        except Exception:
            log.exception("twilio send_sms failed", extra={"to": to})
            return False

    async def redirect_call(self, *, call_sid: str, twiml_url: str) -> bool:
        if self._client is None:
            log.warning(
                "twilio not configured; skipping redirect_call", extra={"call_sid": call_sid}
            )
            return False
        try:
            self._client.calls(call_sid).update(url=twiml_url, method="POST")
            return True
        except Exception:
            log.exception("twilio redirect_call failed", extra={"call_sid": call_sid})
            return False

    async def create_call(self, *, to: str, from_: str, url: str) -> str | None:
        if self._client is None:
            log.warning("twilio not configured; skipping create_call", extra={"to": to})
            return None
        try:
            call = self._client.calls.create(to=to, from_=from_, url=url, method="POST")
            return getattr(call, "sid", None)
        except Exception:
            log.exception("twilio create_call failed", extra={"to": to})
            return None


class NoopTwilioClient:
    """Used in dev/test when Twilio creds aren't set."""

    async def send_sms(self, *, to: str, body: str) -> bool:
        return False

    async def redirect_call(self, *, call_sid: str, twiml_url: str) -> bool:
        return False

    async def create_call(self, *, to: str, from_: str, url: str) -> str | None:
        return None
