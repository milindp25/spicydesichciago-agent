from datetime import datetime, timezone
from typing import Any

import pytest

from app.domain.models import HoursStatus
from app.infrastructure.cache import TtlCache
from app.services.locations_service import LocationsService
from tests.helpers.square_mock import FakeLocationsApi


SAMPLE: list[dict[str, Any]] = [
    {
        "id": "L1",
        "name": "Spicy Desi Loop",
        "address": {
            "address_line_1": "111 W Madison",
            "locality": "Chicago",
            "administrative_district_level_1": "IL",
            "postal_code": "60602",
        },
        "coordinates": {"latitude": 41.881, "longitude": -87.631},
        "business_hours": {
            "periods": [
                {
                    "day_of_week": "MON",
                    "start_local_time": "11:00:00",
                    "end_local_time": "21:30:00",
                },
            ]
        },
        "timezone": "America/Chicago",
    },
]


@pytest.fixture
def svc() -> LocationsService:
    return LocationsService(api=FakeLocationsApi(SAMPLE), cache=TtlCache(ttl_seconds=60))


async def test_list_locations(svc: LocationsService) -> None:
    out = await svc.list_locations()
    assert len(out) == 1
    assert out[0].location_id == "L1"
    assert "Madison" in out[0].address


async def test_hours_today_open_at_2pm_monday(svc: LocationsService) -> None:
    monday2pm = datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc)
    h = await svc.get_hours_today("L1", now=monday2pm)
    assert h.open == "11:00"
    assert h.close == "21:30"
    assert h.status == HoursStatus.OPEN


async def test_hours_today_closed_early_morning(svc: LocationsService) -> None:
    monday6am = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    h = await svc.get_hours_today("L1", now=monday6am)
    assert h.status == HoursStatus.CLOSED


async def test_address(svc: LocationsService) -> None:
    a = await svc.get_address("L1")
    assert "Madison" in a.formatted
    assert a.lat == pytest.approx(41.881)


async def test_unknown_location_raises(svc: LocationsService) -> None:
    with pytest.raises(KeyError):
        await svc.get_hours_today("Lnope")
