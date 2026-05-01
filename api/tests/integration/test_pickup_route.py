from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from app.api.dependencies import AppState

# A location with hours Mon 11:00-21:30, Thu 17:00-21:00, Fri 11:00-22:30 — closed other days.
SAMPLE: list[dict[str, Any]] = [
    {
        "id": "L1",
        "name": "29th Street Near PS",
        "address": {"address_line_1": "29th & Halsted"},
        "business_hours": {
            "periods": [
                {
                    "day_of_week": "MON",
                    "start_local_time": "11:00:00",
                    "end_local_time": "21:30:00",
                },
                {
                    "day_of_week": "THU",
                    "start_local_time": "17:00:00",
                    "end_local_time": "21:00:00",
                },
                {
                    "day_of_week": "FRI",
                    "start_local_time": "11:00:00",
                    "end_local_time": "22:30:00",
                },
            ]
        },
        "timezone": "America/Chicago",
    },
    {
        "id": "L2",
        "name": "Spicy Desi Chicago",
        "address": {"address_line_1": "Main HQ"},
        "business_hours": {"periods": []},
        "timezone": "America/Chicago",
    },
]


def _set_pickup(c: TestClient, headers: dict[str, str], location_id: str) -> None:
    r = c.post(
        "/api/admin/pickup",
        headers=headers,
        json={"tenant": "spicy-desi", "location_id": location_id},
    )
    assert r.status_code == 200


def test_pickup_today_returns_null_when_unset(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/pickup/today?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"pickup": None}


def test_set_pickup_then_read(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    _set_pickup(c, auth_headers, "L1")

    # Monday 14:00 Chicago = 20:00 UTC — within 11:00-21:30 window.
    r = c.get(
        "/api/pickup/today?tenant=spicy-desi&now=2026-01-05T20:00:00Z",
        headers=auth_headers,
    )
    assert r.status_code == 200
    pickup = r.json()["pickup"]
    assert pickup["location_id"] == "L1"
    assert pickup["name"] == "29th Street Near PS"
    assert pickup["hours"]["is_open_now"] is True
    assert pickup["hours"]["close_human"] == "9:30 PM"
    assert "open today at 29th Street Near PS until 9:30 PM Central" in pickup["summary"]


def test_pickup_summary_when_closed_now_but_opens_later_today(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    _set_pickup(c, auth_headers, "L1")

    # Monday 09:00 Chicago = 15:00 UTC — before opening (11:00).
    r = c.get(
        "/api/pickup/today?tenant=spicy-desi&now=2026-01-05T15:00:00Z",
        headers=auth_headers,
    )
    pickup = r.json()["pickup"]
    assert pickup["hours"]["is_open_now"] is False
    assert "opens today at 11:00 AM Central" in pickup["summary"]


def test_pickup_summary_when_closed_today_with_next_open(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    _set_pickup(c, auth_headers, "L1")

    # Tuesday Chicago — location has no Tue hours; next open = Thursday 17:00.
    r = c.get(
        "/api/pickup/today?tenant=spicy-desi&now=2026-01-06T20:00:00Z",
        headers=auth_headers,
    )
    pickup = r.json()["pickup"]
    assert pickup["hours"]["is_open_now"] is False
    assert pickup["hours"]["next_open_weekday"] == "Thursday"
    assert pickup["hours"]["next_open_time_human"] == "5:00 PM"
    assert "Thursday at 5:00 PM Central" in pickup["summary"]


def test_pickup_summary_when_no_upcoming_hours(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    _set_pickup(c, auth_headers, "L2")

    r = c.get(
        "/api/pickup/today?tenant=spicy-desi&now=2026-01-06T20:00:00Z",
        headers=auth_headers,
    )
    pickup = r.json()["pickup"]
    assert pickup["hours"]["is_open_now"] is False
    assert "don't have upcoming hours" in pickup["summary"]


def test_set_pickup_unknown_location_returns_404(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.post(
        "/api/admin/pickup",
        headers=auth_headers,
        json={"tenant": "spicy-desi", "location_id": "Lnope"},
    )
    assert r.status_code == 404


def test_set_pickup_unknown_tenant_returns_404(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.post(
        "/api/admin/pickup",
        headers=auth_headers,
        json={"tenant": "nope", "location_id": "L1"},
    )
    assert r.status_code == 404


def test_set_pickup_requires_auth(
    client_factory: Callable[..., tuple[TestClient, AppState]],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.post(
        "/api/admin/pickup",
        json={"tenant": "spicy-desi", "location_id": "L1"},
    )
    assert r.status_code == 401
