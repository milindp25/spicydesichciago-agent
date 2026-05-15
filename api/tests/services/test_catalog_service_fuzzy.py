"""Fuzzy search behavior on :class:`CatalogService.search_menu`.

These tests pin the caller-facing UX: callers mispronounce items and say
plurals, and the fuzzy matcher should still surface the right dishes,
best match first.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.infrastructure.cache import TtlCache
from app.services.catalog_service import CatalogService
from tests.helpers.square_mock import FakeCatalogApi


def _item(
    name: str,
    *,
    description: str = "",
    category_id: str = "MAINS",
    amount: int = 999,
    item_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": item_id or f"I-{name}",
        "type": "ITEM",
        "item_data": {
            "name": name,
            "description": description,
            "categories": [{"id": category_id}],
            "variations": [
                {
                    "id": f"V-{name}",
                    "item_variation_data": {
                        "price_money": {"amount": amount, "currency": "USD"}
                    },
                }
            ],
        },
    }


CATEGORIES: list[dict[str, Any]] = [
    {"id": "CHAAT", "category_data": {"name": "Chaat"}},
    {"id": "MAINS", "category_data": {"name": "Mains"}},
    {"id": "BIRYANI", "category_data": {"name": "Biryani"}},
    {"id": "STARTERS", "category_data": {"name": "Starters"}},
]

ITEMS: list[dict[str, Any]] = [
    _item("Samosa", description="Crispy fried pastry with potato filling",
          category_id="STARTERS", item_id="I1"),
    _item("Chicken Biryani", description="Long-grain basmati rice with spiced chicken",
          category_id="BIRYANI", item_id="I2"),
    _item("Chicken Curry", description="Boneless chicken in onion-tomato gravy",
          category_id="MAINS", item_id="I3"),
    _item("Pani Puri", description="Hollow shells with tangy water",
          category_id="CHAAT", item_id="I4"),
    _item("Bhel", description="Puffed rice with chutneys", category_id="CHAAT",
          item_id="I5"),
    _item("Paneer Tikka", description="Grilled paneer cubes; samosa-spice rub on the side",
          category_id="STARTERS", item_id="I6"),
]


@pytest.fixture
def svc() -> CatalogService:
    return CatalogService(
        api=FakeCatalogApi(ITEMS, categories=CATEGORIES),
        cache=TtlCache(ttl_seconds=60),
        specials_category_id="SPECIALS",
    )


async def test_exact_match(svc: CatalogService) -> None:
    names = [m.name for m in await svc.search_menu("samosa")]
    assert "Samosa" in names


async def test_plural_matches(svc: CatalogService) -> None:
    names = [m.name for m in await svc.search_menu("samosas")]
    assert "Samosa" in names


async def test_mispronunciation_samosaa(svc: CatalogService) -> None:
    names = [m.name for m in await svc.search_menu("samosaa")]
    assert "Samosa" in names


async def test_mispronunciation_biriyani(svc: CatalogService) -> None:
    names = [m.name for m in await svc.search_menu("biriyani")]
    assert "Chicken Biryani" in names


async def test_category_match(svc: CatalogService) -> None:
    """'chaat' matches items whose category is Chaat even when name has no overlap."""
    names = [m.name for m in await svc.search_menu("chaat")]
    # Pani Puri and Bhel both live under the Chaat category.
    assert "Pani Puri" in names
    assert "Bhel" in names


async def test_empty_query_returns_all(svc: CatalogService) -> None:
    all_names = {m.name for m in await svc.search_menu("")}
    assert all_names == {i["item_data"]["name"] for i in ITEMS}


async def test_whitespace_query_returns_all(svc: CatalogService) -> None:
    all_names = {m.name for m in await svc.search_menu("   ")}
    assert all_names == {i["item_data"]["name"] for i in ITEMS}


async def test_unrelated_query_returns_empty(svc: CatalogService) -> None:
    assert await svc.search_menu("pizza") == []


async def test_multi_word_reordering(svc: CatalogService) -> None:
    """Token-set scoring handles word reordering."""
    names = [m.name for m in await svc.search_menu("curry chicken")]
    assert "Chicken Curry" in names


async def test_ranking_exact_before_description_hit(svc: CatalogService) -> None:
    """'samosa' should rank the literal 'Samosa' above 'Paneer Tikka' whose
    description merely references samosa-spice."""
    results = await svc.search_menu("samosa")
    assert results, "expected at least one match"
    assert results[0].name == "Samosa"
