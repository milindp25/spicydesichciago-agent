from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)


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

    async def list_full_menu(self, category: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"tenant": self._tenant}
        if category:
            params["category"] = category
        r = await self._client.get("/api/menu/list", params=params)
        r.raise_for_status()
        return r.json()

    async def list_menu_categories(self) -> dict[str, Any]:
        r = await self._client.get(
            "/api/menu/categories", params={"tenant": self._tenant}
        )
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

    async def send_sms_link(
        self, *, call_sid: str, to: str, kind: str
    ) -> dict[str, Any]:
        r = await self._client.post(
            "/api/sms/send-link",
            json={"call_sid": call_sid, "to": to, "kind": kind},
        )
        r.raise_for_status()
        return r.json()

    async def get_caller_history(self, *, phone: str) -> dict[str, Any]:
        r = await self._client.get("/api/callers/history", params={"phone": phone})
        r.raise_for_status()
        return r.json()

    async def append_event(self, *, call_sid: str, kind: str, payload: dict[str, Any]) -> None:
        await self._client.post(
            f"/api/calls/{call_sid}/event",
            json={"kind": kind, "payload": payload},
        )

    async def record_call_start(
        self,
        *,
        call_sid: str,
        started_at: datetime,
        caller_phone: str,
        from_number: str,
    ) -> None:
        """Best-effort: record call start. Never raises."""
        try:
            await self._client.post(
                f"/api/calls/{call_sid}/start",
                json={
                    "started_at": started_at.isoformat(),
                    "caller_phone": caller_phone,
                    "from_number": from_number,
                },
            )
        except Exception:
            log.exception("record_call_start failed for %s", call_sid)

    async def record_call_end(
        self,
        *,
        call_sid: str,
        ended_at: datetime,
        outcome: str,
        duration_ms: int,
        caller_phone: str = "",
        from_number: str = "",
    ) -> None:
        """Best-effort: record call end. Never raises."""
        try:
            await self._client.post(
                f"/api/calls/{call_sid}/end",
                json={
                    "ended_at": ended_at.isoformat(),
                    "outcome": outcome,
                    "duration_ms": duration_ms,
                    "caller_phone": caller_phone,
                    "from_number": from_number,
                },
            )
        except Exception:
            log.exception("record_call_end failed for %s", call_sid)

    async def record_call_summary(self, *, call_sid: str, summary: str) -> None:
        """Best-effort: record call summary. Never raises."""
        try:
            await self._client.post(
                f"/api/calls/{call_sid}/summary",
                json={"summary": summary},
            )
        except Exception:
            log.exception("record_call_summary failed for %s", call_sid)

    async def aclose(self) -> None:
        await self._client.aclose()
