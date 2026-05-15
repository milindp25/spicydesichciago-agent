from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import HoursToday, PickupToday
from app.domain.pickup import PickupRecord
from app.infrastructure.firestore_pickup_state_store import FirestorePickupStateStore
from app.services.locations_service import LocationsService


def _spot(name: str, address: str) -> str:
    address = (address or "").strip()
    if address:
        return f"{name}, at {address}"
    return name


def _build_summary(name: str, address: str, hours: HoursToday | None) -> str:
    spot = _spot(name, address)
    if hours is None:
        return f"We're set up at {spot} today — not sure on hours though."

    tz = hours.tz_label
    if hours.is_open_now and hours.close_human:
        return f"We're open right now at {spot}, until {hours.close_human} {tz}."

    if hours.open_human and hours.close_human and hours.open is not None:
        if hours.next_open_weekday and hours.next_open_time_human:
            today_name = datetime.now(UTC).astimezone().strftime("%A")
            if hours.next_open_time == hours.open:
                return (
                    f"We're not open yet today — we'll be at {spot} "
                    f"starting {hours.open_human} {tz}."
                )
            _ = today_name
            return (
                f"We're done for today. Next we'll be at {spot} "
                f"on {hours.next_open_weekday} at {hours.next_open_time_human} {tz}."
            )
        return (
            f"We're between hours right now — {spot} is open today from "
            f"{hours.open_human} to {hours.close_human} {tz}."
        )

    if hours.next_open_weekday and hours.next_open_time_human:
        return (
            f"We're closed today, but next we'll be at {spot} "
            f"{hours.next_open_weekday} at {hours.next_open_time_human} {tz}."
        )
    return f"We're at {spot} today but I don't have upcoming hours on file."


class PickupService:
    """Resolves the active pickup location by combining stored state with live Square data."""

    def __init__(
        self, store: FirestorePickupStateStore, locations: LocationsService
    ) -> None:
        self._store = store
        self._locations = locations

    async def get_today(self, tenant_slug: str, now: datetime | None = None) -> PickupToday | None:
        record = self._store.get(tenant_slug)
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
            set_at=record.set_at.isoformat(),
            set_for_date=record.set_for_date,
            hours=hours,
            summary=_build_summary(match.name, match.address, hours),
        )

    async def set_today(self, tenant_slug: str, location_id: str) -> PickupRecord:
        all_locations = await self._locations.list_locations()
        if not any(loc.location_id == location_id for loc in all_locations):
            raise KeyError(f"location not found: {location_id}")
        now = datetime.now(UTC)
        record = PickupRecord(
            location_id=location_id,
            set_at=now,
            set_for_date=now.date().isoformat(),
        )
        self._store.set(tenant_slug, record)
        return record
