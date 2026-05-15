from __future__ import annotations

from typing import Any

from rapidfuzz import fuzz

from app.domain.models import MenuItem
from app.infrastructure.cache import TtlCache
from app.infrastructure.square_client import CatalogApi

# Minimum fuzzy-match score (0-100) for an item to count as a query hit.
# Tuned to catch mispronunciations ("samosaa") and plurals ("samosas")
# without flooding callers with unrelated results.
MENU_SEARCH_THRESHOLD = 70


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


def _score_item(item: MenuItem, query: str) -> int:
    """Return a 0-100 fuzzy match score for ``item`` against ``query``.

    Combines ``partial_ratio`` (handles single tokens / substrings / minor
    misspellings) and ``token_set_ratio`` (handles multi-word queries where
    the words appear in a different order). We score the *name* on its own
    and the full haystack (name + description + category) separately, then
    favor the name slightly so a direct name hit ranks above an item that
    only mentions the query in its description or category.
    """
    q = query.lower().strip()
    if not q:
        return 0
    name = item.name.lower()
    haystack = " ".join(
        [
            name,
            (item.description or "").lower(),
            (item.category or "").lower(),
        ]
    ).strip()
    if not haystack:
        return 0
    name_score = max(fuzz.partial_ratio(q, name), fuzz.token_set_ratio(q, name)) if name else 0
    full_score = max(fuzz.partial_ratio(q, haystack), fuzz.token_set_ratio(q, haystack))
    # Discount non-name hits so a literal name match always sorts above an
    # item that only mentions the query in its description/category.
    return int(max(name_score, full_score * 0.9))


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
        if not query.strip():
            return menu
        scored = [(m, _score_item(m, query)) for m in menu]
        scored = [(m, s) for m, s in scored if s >= MENU_SEARCH_THRESHOLD]
        # Sort by score desc, then alphabetically by name as deterministic tiebreaker.
        scored.sort(key=lambda ms: (-ms[1], ms[0].name.lower()))
        return [m for m, _ in scored]

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
