from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import PickupToday
from app.infrastructure.pickup_state import PickupRecord, PickupStateStore
from app.services.locations_service import LocationsService


class PickupService:
    """Resolves the active pickup location by combining stored state with live Square data."""

    def __init__(self, store: PickupStateStore, locations: LocationsService) -> None:
        self._store = store
        self._locations = locations

    async def get_today(self, tenant_slug: str) -> PickupToday | None:
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
            hours = await self._locations.get_hours_today(record.location_id)
        except KeyError:
            hours = None
        return PickupToday(
            location_id=match.location_id,
            name=match.name,
            address=match.address,
            set_at=record.set_at,
            set_for_date=record.set_for_date,
            hours=hours,
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
