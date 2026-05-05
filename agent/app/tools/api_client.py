from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

# One quick retry on transient failures (5xx or network blip). Tools run on
# the conversation hot path — a missed retry means the caller hears "I'm
# having trouble with that" instead of an answer.
_RETRY_STATUS = {500, 502, 503, 504}
_RETRY_BACKOFF_SECS = 0.2


async def _request_with_retry(
    client: httpx.AsyncClient, method: str, url: str, **kwargs: Any
) -> httpx.Response:
    try:
        r = await client.request(method, url, **kwargs)
        if r.status_code in _RETRY_STATUS:
            raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
        return r
    except (httpx.TransportError, httpx.HTTPStatusError) as exc:
        log.warning("api retry: %s %s — %s", method, url, exc)
        await asyncio.sleep(_RETRY_BACKOFF_SECS)
        return await client.request(method, url, **kwargs)


class ApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        secret: str,
        tenant: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Tools-Auth": secret},
            timeout=10.0,
            transport=transport,
        )
        self._tenant = tenant

    async def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await _request_with_retry(self._client, "GET", url, **kwargs)

    async def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await _request_with_retry(self._client, "POST", url, **kwargs)

    async def get_pickup_today(self) -> dict[str, Any]:
        r = await self._get("/api/pickup/today", params={"tenant": self._tenant})
        r.raise_for_status()
        return r.json()

    async def search_menu(self, query: str) -> dict[str, Any]:
        r = await self._get("/api/menu/search", params={"tenant": self._tenant, "q": query})
        r.raise_for_status()
        return r.json()

    async def list_full_menu(self, category: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"tenant": self._tenant}
        if category:
            params["category"] = category
        r = await self._get("/api/menu/list", params=params)
        r.raise_for_status()
        return r.json()

    async def list_menu_categories(self) -> dict[str, Any]:
        r = await self._get(
            "/api/menu/categories", params={"tenant": self._tenant}
        )
        r.raise_for_status()
        return r.json()

    async def get_specials(self) -> dict[str, Any]:
        r = await self._get("/api/specials", params={"tenant": self._tenant})
        r.raise_for_status()
        return r.json()

    async def take_message(
        self,
        *,
        call_sid: str,
        callback_number: str,
        reason: str,
        caller_name: str | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        r = await self._post(
            "/api/messages",
            json={
                "call_sid": call_sid,
                "callback_number": callback_number,
                "reason": reason,
                "caller_name": caller_name,
                "language": language,
            },
        )
        r.raise_for_status()
        return r.json()

    async def request_transfer(self, *, call_sid: str, reason: str | None = None) -> dict[str, Any]:
        r = await self._post(
            "/api/transfers",
            json={"call_sid": call_sid, "reason": reason},
        )
        r.raise_for_status()
        return r.json()

    async def send_sms_link(
        self, *, call_sid: str, to: str, kind: str
    ) -> dict[str, Any]:
        r = await self._post(
            "/api/sms/send-link",
            json={"call_sid": call_sid, "to": to, "kind": kind},
        )
        r.raise_for_status()
        return r.json()

    async def get_caller_history(self, *, phone: str) -> dict[str, Any]:
        r = await self._get("/api/callers/history", params={"phone": phone})
        r.raise_for_status()
        return r.json()

    async def get_tenant(self) -> dict[str, Any]:
        r = await self._get("/api/tenant", params={"tenant": self._tenant})
        r.raise_for_status()
        return r.json()

    async def append_event(self, *, call_sid: str, kind: str, payload: dict[str, Any]) -> None:
        # Fire-and-forget; don't retry — losing one event isn't worth blocking
        # the caller's audio path.
        await self._client.post(
            f"/api/calls/{call_sid}/event",
            json={"kind": kind, "payload": payload},
        )

    async def aclose(self) -> None:
        await self._client.aclose()
