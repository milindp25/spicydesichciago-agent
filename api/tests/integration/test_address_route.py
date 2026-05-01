from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from app.api.dependencies import AppState

SAMPLE: list[dict[str, Any]] = [
    {
        "id": "L1",
        "name": "Loop",
        "address": {"address_line_1": "111 W Madison", "locality": "Chicago"},
        "coordinates": {"latitude": 41.881, "longitude": -87.631},
        "business_hours": {"periods": []},
    },
]


def test_returns_address(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations/L1/address?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "Madison" in body["formatted"]
    assert body["lat"] == 41.881


def test_unknown_returns_404(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations/Lnope/address?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 404
