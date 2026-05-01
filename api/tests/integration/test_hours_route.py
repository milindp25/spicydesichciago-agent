from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from app.api.dependencies import AppState

SAMPLE: list[dict[str, Any]] = [
    {
        "id": "L1",
        "name": "Loop",
        "address": {"address_line_1": "X"},
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


def test_returns_hours(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get(
        "/api/locations/L1/hours/today?tenant=spicy-desi&now=2026-01-05T20:00:00Z",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["open"] == "11:00"
    assert body["close"] == "21:30"
    assert body["status"] in ("open", "closed", "closing_soon")


def test_unknown_location_returns_404(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get(
        "/api/locations/Lnope/hours/today?tenant=spicy-desi", headers=auth_headers
    )
    assert r.status_code == 404
