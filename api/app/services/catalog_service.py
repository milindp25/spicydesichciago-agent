from __future__ import annotations

from typing import Any

from app.domain.models import MenuItem
from app.infrastructure.cache import TtlCache
from app.infrastructure.square_client import CatalogApi


def _format_price(amount: int | None, currency: str | None) -> str:
    if amount is None:
        return ""
    value = amount / 100
    if currency == "USD":
        return f"${value:.2f}"
    return f"{value:.2f} {currency or ''}".strip()


def _to_menu_item(raw: dict[str, Any], category_names: dict[str, str]) -> MenuItem:
    item_data = raw.get("item_data") or {}
    variations = item_data.get("variations") or []
    price_money = (
        (variations[0].get("item_variation_data") or {}).get("price_money") or {}
        if variations
        else {}
    )
    categories = item_data.get("categories") or []
    category_id = categories[0]["id"] if categories else None
    category = category_names.get(category_id, category_id) if category_id else None
    return MenuItem(
        name=item_data.get("name") or "",
        description=item_data.get("description") or "",
        price=_format_price(price_money.get("amount"), price_money.get("currency")),
        category=category,
        dietary_tags=[],
    )


def _matches_query(item: MenuItem, query: str) -> bool:
    q = query.lower().strip()
    if not q:
        return True
    haystack = " ".join(
        [
            item.name.lower(),
            (item.description or "").lower(),
            (item.category or "").lower(),
        ]
    )
    return q in haystack


class CatalogService:
    def __init__(
        self,
        api: CatalogApi,
        cache: TtlCache[list[dict[str, Any]]],
        specials_category_id: str,
    ) -> None:
        self._api = api
        self._cache = cache
        self._specials_id = specials_category_id

    async def _category_names(self) -> dict[str, str]:
        async def loader() -> list[dict[str, Any]]:
            return await self._api.list_categories()

        cats = await self._cache.get_or_load("categories", loader)
        out: dict[str, str] = {}
        for c in cats:
            cid = c.get("id")
            name = (c.get("category_data") or {}).get("name")
            if cid and name:
                out[cid] = name
        return out

    async def search_menu(self, query: str) -> list[MenuItem]:
        # Pull all items and filter ourselves so a category keyword like "chaat"
        # matches items whose Square category name is "Chaat" even if the item
        # name doesn't contain that word.
        async def loader() -> list[dict[str, Any]]:
            return await self._api.search_items()

        all_items = await self._cache.get_or_load("all_items", loader)
        cat_names = await self._category_names()
        menu = [_to_menu_item(i, cat_names) for i in all_items]
        return [m for m in menu if _matches_query(m, query)]

    async def list_all_menu(self) -> list[MenuItem]:
        async def loader() -> list[dict[str, Any]]:
            return await self._api.search_items()

        all_items = await self._cache.get_or_load("all_items", loader)
        cat_names = await self._category_names()
        return [_to_menu_item(i, cat_names) for i in all_items]

    async def get_specials(self) -> list[MenuItem]:
        async def loader() -> list[dict[str, Any]]:
            return await self._api.search_items(category_ids=[self._specials_id])

        items = await self._cache.get_or_load("specials", loader)
        cat_names = await self._category_names()
        return [_to_menu_item(i, cat_names) for i in items]

    def invalidate(self) -> None:
        self._cache.clear()
