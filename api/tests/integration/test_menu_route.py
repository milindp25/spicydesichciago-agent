from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from app.api.dependencies import AppState

ITEMS: list[dict[str, Any]] = [
    {
        "id": "I1",
        "type": "ITEM",
        "item_data": {
            "name": "Chicken Tikka Masala",
            "description": "creamy tomato",
            "categories": [{"id": "MAINS"}],
            "variations": [
                {
                    "id": "V1",
                    "item_variation_data": {"price_money": {"amount": 1899, "currency": "USD"}},
                }
            ],
        },
    }
]


def test_returns_match(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(catalog_items=ITEMS)
    r = c.get(
        "/api/menu/search?tenant=spicy-desi&q=tikka",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["items"][0]["name"] == "Chicken Tikka Masala"


def test_requires_q(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(catalog_items=ITEMS)
    r = c.get("/api/menu/search?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 400


def test_unknown_tenant_returns_404(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(catalog_items=ITEMS)
    r = c.get("/api/menu/search?tenant=nope&q=tikka", headers=auth_headers)
    assert r.status_code == 404
