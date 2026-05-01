from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.models import AddressInfo, HoursStatus, HoursToday, LocationListItem
from app.infrastructure.cache import TtlCache
from app.infrastructure.square_client import LocationsApi


def _format_address(addr: dict[str, Any] | None) -> str:
    if not addr:
        return ""
    parts = [
        addr.get("address_line_1"),
        addr.get("locality"),
        addr.get("administrative_district_level_1"),
        addr.get("postal_code"),
    ]
    return ", ".join(p for p in parts if p)


def _hhmm(value: str | None) -> str | None:
    return value[:5] if value else None


def _to_minutes(hhmm_str: str) -> int:
    h, m = (int(x) for x in hhmm_str.split(":"))
    return h * 60 + m


class LocationsService:
    def __init__(self, api: LocationsApi, cache: TtlCache[list[dict[str, Any]]]) -> None:
        self._api = api
        self._cache = cache

    async def _all(self) -> list[dict[str, Any]]:
        return await self._cache.get_or_load("all", self._api.list_locations)

    async def list_locations(self) -> list[LocationListItem]:
        return [
            LocationListItem(
                location_id=loc["id"],
                name=loc["name"],
                address=_format_address(loc.get("address")),
            )
            for loc in await self._all()
        ]

    async def get_hours_today(self, location_id: str, now: datetime | None = None) -> HoursToday:
        loc = await self._find(location_id)
        tz = ZoneInfo(loc.get("timezone") or "America/Chicago")
        cur = (now or datetime.now(UTC)).astimezone(tz)
        dow = cur.strftime("%a").upper()
        period = next(
            (
                p
                for p in loc.get("business_hours", {}).get("periods", [])
                if p.get("day_of_week") == dow
            ),
            None,
        )
        if period is None:
            return HoursToday(open=None, close=None, status=HoursStatus.CLOSED)
        open_str = _hhmm(period.get("start_local_time"))
        close_str = _hhmm(period.get("end_local_time"))
        cur_str = cur.strftime("%H:%M")
        status = HoursStatus.CLOSED
        if open_str and close_str and open_str <= cur_str < close_str:
            if _to_minutes(close_str) - _to_minutes(cur_str) <= 30:
                status = HoursStatus.CLOSING_SOON
            else:
                status = HoursStatus.OPEN
        return HoursToday(open=open_str, close=close_str, status=status)

    async def get_address(self, location_id: str) -> AddressInfo:
        loc = await self._find(location_id)
        coords = loc.get("coordinates") or {}
        return AddressInfo(
            formatted=_format_address(loc.get("address")),
            lat=coords.get("latitude"),
            lng=coords.get("longitude"),
        )

    def cache(self) -> TtlCache[list[dict[str, Any]]]:
        return self._cache

    async def _find(self, location_id: str) -> dict[str, Any]:
        for loc in await self._all():
            if loc["id"] == location_id:
                return loc
        raise KeyError(f"location not found: {location_id}")
