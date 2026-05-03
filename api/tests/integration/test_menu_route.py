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


CHAAT_ITEMS: list[dict[str, Any]] = [
    {
        "id": "I_PP",
        "type": "ITEM",
        "item_data": {
            "name": "Pani Puri",
            "description": "tangy",
            "categories": [{"id": "CAT_CHAAT"}],
            "variations": [
                {
                    "id": "V",
                    "item_variation_data": {"price_money": {"amount": 899, "currency": "USD"}},
                }
            ],
        },
    },
    {
        "id": "I_AT",
        "type": "ITEM",
        "item_data": {
            "name": "Aloo Tikka Chaat",
            "description": "",
            "categories": [{"id": "CAT_CHAAT"}],
            "variations": [
                {
                    "id": "V",
                    "item_variation_data": {"price_money": {"amount": 799, "currency": "USD"}},
                }
            ],
        },
    },
    {
        "id": "I_DOSA",
        "type": "ITEM",
        "item_data": {
            "name": "Masala Dosa",
            "description": "",
            "categories": [{"id": "CAT_SI"}],
            "variations": [
                {
                    "id": "V",
                    "item_variation_data": {"price_money": {"amount": 1099, "currency": "USD"}},
                }
            ],
        },
    },
]
CHAAT_CATS: list[dict[str, Any]] = [
    {"id": "CAT_CHAAT", "type": "CATEGORY", "category_data": {"name": "Chaat"}},
    {"id": "CAT_SI", "type": "CATEGORY", "category_data": {"name": "South Indian"}},
]


def test_search_by_category_name_finds_pani_puri(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(catalog_items=CHAAT_ITEMS, catalog_categories=CHAAT_CATS)
    r = c.get(
        "/api/menu/search?tenant=spicy-desi&q=chaat",
        headers=auth_headers,
    )
    assert r.status_code == 200
    names = {i["name"] for i in r.json()["items"]}
    # Pani Puri's name doesn't contain "chaat" but its category is "Chaat".
    assert names == {"Pani Puri", "Aloo Tikka Chaat"}


def test_search_resolves_category_to_human_name(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(catalog_items=CHAAT_ITEMS, catalog_categories=CHAAT_CATS)
    r = c.get(
        "/api/menu/search?tenant=spicy-desi&q=dosa",
        headers=auth_headers,
    )
    item = r.json()["items"][0]
    assert item["name"] == "Masala Dosa"
    assert item["category"] == "South Indian"


def test_list_menu_returns_all_items(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(catalog_items=CHAAT_ITEMS, catalog_categories=CHAAT_CATS)
    r = c.get("/api/menu/list?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert {i["name"] for i in body["items"]} == {
        "Pani Puri",
        "Aloo Tikka Chaat",
        "Masala Dosa",
    }


def test_list_menu_unknown_tenant_404(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(catalog_items=CHAAT_ITEMS)
    r = c.get("/api/menu/list?tenant=nope", headers=auth_headers)
    assert r.status_code == 404
