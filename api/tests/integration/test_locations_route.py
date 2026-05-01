from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from app.api.dependencies import AppState

SAMPLE: list[dict[str, Any]] = [
    {
        "id": "L1",
        "name": "Loop",
        "address": {"address_line_1": "111 W Madison"},
        "business_hours": {"periods": []},
    },
]


def test_requires_auth(
    client_factory: Callable[..., tuple[TestClient, AppState]],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations?tenant=spicy-desi")
    assert r.status_code == 401


def test_missing_tenant_returns_400(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations", headers=auth_headers)
    assert r.status_code == 400


def test_unknown_tenant_returns_404(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations?tenant=nope", headers=auth_headers)
    assert r.status_code == 404


def test_returns_locations(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["locations"][0]["location_id"] == "L1"
