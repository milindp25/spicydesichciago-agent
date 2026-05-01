from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from app.api.dependencies import AppState

SAMPLE: list[dict[str, Any]] = [
    {
        "id": "L1",
        "name": "29th Street Near PS",
        "address": {"address_line_1": "29th & Halsted"},
        "business_hours": {"periods": []},
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
    r = c.post(
        "/api/admin/pickup",
        headers=auth_headers,
        json={"tenant": "spicy-desi", "location_id": "L1"},
    )
    assert r.status_code == 200
    assert r.json()["location_id"] == "L1"

    r = c.get("/api/pickup/today?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 200
    pickup = r.json()["pickup"]
    assert pickup["location_id"] == "L1"
    assert pickup["name"] == "29th Street Near PS"
    assert "29th" in pickup["address"]


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
