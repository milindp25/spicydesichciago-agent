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


def _to_menu_item(raw: dict[str, Any]) -> MenuItem:
    item_data = raw.get("item_data") or {}
    variations = item_data.get("variations") or []
    price_money = (
        (variations[0].get("item_variation_data") or {}).get("price_money") or {}
        if variations
        else {}
    )
    categories = item_data.get("categories") or []
    return MenuItem(
        name=item_data.get("name") or "",
        description=item_data.get("description") or "",
        price=_format_price(price_money.get("amount"), price_money.get("currency")),
        category=categories[0]["id"] if categories else None,
        dietary_tags=[],
    )


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

    async def search_menu(self, query: str) -> list[MenuItem]:
        items = await self._api.search_items(text_filter=query)
        return [_to_menu_item(i) for i in items]

    async def get_specials(self) -> list[MenuItem]:
        async def loader() -> list[dict[str, Any]]:
            return await self._api.search_items(category_ids=[self._specials_id])

        items = await self._cache.get_or_load("specials", loader)
        return [_to_menu_item(i) for i in items]

    def invalidate(self) -> None:
        self._cache.clear()
