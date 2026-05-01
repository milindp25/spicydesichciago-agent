from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import HoursToday, PickupToday
from app.infrastructure.pickup_state import PickupRecord, PickupStateStore
from app.services.locations_service import LocationsService


def _build_summary(name: str, hours: HoursToday | None) -> str:
    if hours is None:
        return (
            f"Today's pickup spot is {name}, but we don't have hours information for it right now."
        )

    tz = hours.tz_label
    if hours.is_open_now and hours.close_human:
        return f"We're open today at {name} until {hours.close_human} {tz}."

    # Not open right now.
    if hours.open_human and hours.close_human and hours.open is not None:
        # Today has hours but we're outside them. Two cases: before opening, or after closing.
        # If next_open is today (same day), say so explicitly.
        if hours.next_open_weekday and hours.next_open_time_human:
            today_name = (
                datetime.now(UTC).astimezone().strftime("%A")
            )  # rough; replaced by a precise check via next_open vs today's open below
            if hours.next_open_time == hours.open:
                return f"We're closed right now. {name} opens today at {hours.open_human} {tz}."
            _ = today_name
            return (
                f"We're closed right now. Next open at {name}: "
                f"{hours.next_open_weekday} at {hours.next_open_time_human} {tz}."
            )
        return (
            f"We're closed right now. {name} is open today from "
            f"{hours.open_human} to {hours.close_human} {tz}."
        )

    # No hours today at all.
    if hours.next_open_weekday and hours.next_open_time_human:
        return (
            f"We're closed today. Next open at {name}: "
            f"{hours.next_open_weekday} at {hours.next_open_time_human} {tz}."
        )
    return f"We're closed today at {name}, and I don't have upcoming hours on file."


class PickupService:
    """Resolves the active pickup location by combining stored state with live Square data."""

    def __init__(self, store: PickupStateStore, locations: LocationsService) -> None:
        self._store = store
        self._locations = locations

    async def get_today(self, tenant_slug: str, now: datetime | None = None) -> PickupToday | None:
        record = await self._store.get(tenant_slug)
        if record is None:
            return None
        all_locations = await self._locations.list_locations()
        match = next(
            (loc for loc in all_locations if loc.location_id == record.location_id),
            None,
        )
        if match is None:
            return None
        try:
            hours = await self._locations.get_hours_today(record.location_id, now=now)
        except KeyError:
            hours = None
        return PickupToday(
            location_id=match.location_id,
            name=match.name,
            address=match.address,
            set_at=record.set_at,
            set_for_date=record.set_for_date,
            hours=hours,
            summary=_build_summary(match.name, hours),
        )

    async def set_today(self, tenant_slug: str, location_id: str) -> PickupRecord:
        all_locations = await self._locations.list_locations()
        if not any(loc.location_id == location_id for loc in all_locations):
            raise KeyError(f"location not found: {location_id}")
        now = datetime.now(UTC)
        record = PickupRecord(
            location_id=location_id,
            set_at=now.isoformat(),
            set_for_date=now.date().isoformat(),
        )
        await self._store.set(tenant_slug, record)
        return record
