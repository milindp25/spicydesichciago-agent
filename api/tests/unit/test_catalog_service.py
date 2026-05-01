from typing import Any

import pytest

from app.infrastructure.cache import TtlCache
from app.services.catalog_service import CatalogService
from tests.helpers.square_mock import FakeCatalogApi

ITEMS: list[dict[str, Any]] = [
    {
        "id": "I1",
        "type": "ITEM",
        "item_data": {
            "name": "Chicken Tikka Masala",
            "description": "Boneless chicken in creamy tomato sauce",
            "categories": [{"id": "MAINS"}],
            "variations": [
                {
                    "id": "V1",
                    "item_variation_data": {"price_money": {"amount": 1899, "currency": "USD"}},
                }
            ],
        },
    },
    {
        "id": "I2",
        "type": "ITEM",
        "item_data": {
            "name": "Paneer Tikka",
            "description": "Grilled paneer cubes",
            "categories": [{"id": "STARTERS"}, {"id": "SPECIALS"}],
            "variations": [
                {
                    "id": "V2",
                    "item_variation_data": {"price_money": {"amount": 1599, "currency": "USD"}},
                }
            ],
        },
    },
]


@pytest.fixture
def svc() -> CatalogService:
    return CatalogService(
        api=FakeCatalogApi(ITEMS),
        cache=TtlCache(ttl_seconds=60),
        specials_category_id="SPECIALS",
    )


async def test_search_menu_finds_match(svc: CatalogService) -> None:
    r = await svc.search_menu("paneer")
    assert len(r) == 1
    assert r[0].name == "Paneer Tikka"
    assert r[0].price == "$15.99"


async def test_search_menu_no_match(svc: CatalogService) -> None:
    assert await svc.search_menu("sushi") == []


async def test_specials_returns_only_tagged(svc: CatalogService) -> None:
    r = await svc.get_specials()
    assert len(r) == 1
    assert r[0].name == "Paneer Tikka"


async def test_handles_null_description_and_categories() -> None:
    """Square sometimes returns description/categories as null (not absent)."""
    items_with_nulls: list[dict[str, Any]] = [
        {
            "id": "I3",
            "type": "ITEM",
            "item_data": {
                "name": "Mystery Item",
                "description": None,
                "categories": None,
                "variations": [
                    {
                        "id": "V3",
                        "item_variation_data": {
                            "price_money": {"amount": 999, "currency": "USD"}
                        },
                    }
                ],
            },
        }
    ]
    svc = CatalogService(
        api=FakeCatalogApi(items_with_nulls),
        cache=TtlCache(ttl_seconds=60),
        specials_category_id="SPECIALS",
    )
    r = await svc.search_menu("mystery")
    assert len(r) == 1
    assert r[0].name == "Mystery Item"
    assert r[0].description == ""
    assert r[0].category is None
    assert r[0].price == "$9.99"
