from __future__ import annotations

from typing import Any

import httpx


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

    async def get_pickup_today(self) -> dict[str, Any]:
        r = await self._client.get("/api/pickup/today", params={"tenant": self._tenant})
        r.raise_for_status()
        return r.json()

    async def search_menu(self, query: str) -> dict[str, Any]:
        r = await self._client.get("/api/menu/search", params={"tenant": self._tenant, "q": query})
        r.raise_for_status()
        return r.json()

    async def list_full_menu(self) -> dict[str, Any]:
        r = await self._client.get("/api/menu/list", params={"tenant": self._tenant})
        r.raise_for_status()
        return r.json()

    async def get_specials(self) -> dict[str, Any]:
        r = await self._client.get("/api/specials", params={"tenant": self._tenant})
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
        r = await self._client.post(
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
        r = await self._client.post(
            "/api/transfers",
            json={"call_sid": call_sid, "reason": reason},
        )
        r.raise_for_status()
        return r.json()

    async def append_event(self, *, call_sid: str, kind: str, payload: dict[str, Any]) -> None:
        await self._client.post(
            f"/api/calls/{call_sid}/event",
            json={"kind": kind, "payload": payload},
        )

    async def aclose(self) -> None:
        await self._client.aclose()
