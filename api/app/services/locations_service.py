from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


def _to_12h(hhmm_str: str | None) -> str | None:
    """'16:30' -> '4:30 PM', '09:00' -> '9:00 AM'."""
    if not hhmm_str:
        return None
    h, m = (int(x) for x in hhmm_str.split(":"))
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def _periods_for_dow(periods: list[dict[str, Any]], dow: str) -> list[dict[str, Any]]:
    return [p for p in periods if p.get("day_of_week") == dow]


def _earliest_open(periods: list[dict[str, Any]]) -> str | None:
    starts = [_hhmm(p.get("start_local_time")) for p in periods]
    starts = [s for s in starts if s]
    return min(starts) if starts else None


def _next_open_after(periods: list[dict[str, Any]], cur: datetime) -> tuple[str, str] | None:
    """Find the next opening time strictly after `cur` within the next 7 days.

    Returns (full_weekday_name, hh:mm) or None if no future opening found.
    Considers only future starts on today's date; remaining days return their
    earliest start.
    """
    cur_dow = cur.strftime("%a").upper()
    cur_hhmm = cur.strftime("%H:%M")

    # Today's remaining starts (after current time).
    today_starts = sorted(
        s
        for s in (_hhmm(p.get("start_local_time")) for p in _periods_for_dow(periods, cur_dow))
        if s and s > cur_hhmm
    )
    if today_starts:
        return (cur.strftime("%A"), today_starts[0])

    # Future days.
    for offset in range(1, 8):
        candidate = cur + timedelta(days=offset)
        dow = candidate.strftime("%a").upper()
        earliest = _earliest_open(_periods_for_dow(periods, dow))
        if earliest:
            return (candidate.strftime("%A"), earliest)
    return None


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
        all_periods = loc.get("business_hours", {}).get("periods", [])
        dow = cur.strftime("%a").upper()
        today_periods = _periods_for_dow(all_periods, dow)

        next_open = _next_open_after(all_periods, cur)
        next_weekday = next_open[0] if next_open else None
        next_time = next_open[1] if next_open else None
        next_time_human = _to_12h(next_time)

        if not today_periods:
            return HoursToday(
                open=None,
                close=None,
                status=HoursStatus.CLOSED,
                is_open_now=False,
                next_open_weekday=next_weekday,
                next_open_time=next_time,
                next_open_time_human=next_time_human,
            )

        # Use the period that covers "now" if any; otherwise the next/earliest one.
        cur_str = cur.strftime("%H:%M")
        active = next(
            (
                p
                for p in today_periods
                if (s := _hhmm(p.get("start_local_time"))) is not None
                and (e := _hhmm(p.get("end_local_time"))) is not None
                and s <= cur_str < e
            ),
            None,
        )
        if active is not None:
            open_str = _hhmm(active.get("start_local_time"))
            close_str = _hhmm(active.get("end_local_time"))
            assert open_str is not None and close_str is not None
            remaining = _to_minutes(close_str) - _to_minutes(cur_str)
            status = HoursStatus.CLOSING_SOON if remaining <= 30 else HoursStatus.OPEN
            return HoursToday(
                open=open_str,
                close=close_str,
                status=status,
                open_human=_to_12h(open_str),
                close_human=_to_12h(close_str),
                is_open_now=True,
                next_open_weekday=next_weekday,
                next_open_time=next_time,
                next_open_time_human=next_time_human,
            )

        # Today has hours but we're outside any period (before first / between / after last).
        open_str = _earliest_open(today_periods)
        close_candidates = [_hhmm(p.get("end_local_time")) for p in today_periods]
        close_candidates = [c for c in close_candidates if c]
        close_str = max(close_candidates) if close_candidates else None
        return HoursToday(
            open=open_str,
            close=close_str,
            status=HoursStatus.CLOSED,
            open_human=_to_12h(open_str),
            close_human=_to_12h(close_str),
            is_open_now=False,
            next_open_weekday=next_weekday,
            next_open_time=next_time,
            next_open_time_human=next_time_human,
        )

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
