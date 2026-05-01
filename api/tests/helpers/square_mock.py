from __future__ import annotations

from typing import Any


class FakeLocationsApi:
    def __init__(self, locations: list[dict[str, Any]]) -> None:
        self._locations = locations

    async def list_locations(self) -> list[dict[str, Any]]:
        return list(self._locations)

    async def retrieve_location(self, location_id: str) -> dict[str, Any] | None:
        for loc in self._locations:
            if loc["id"] == location_id:
                return loc
        return None


class FakeCatalogApi:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    async def search_items(
        self,
        *,
        text_filter: str | None = None,
        category_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        result = list(self._items)
        if text_filter:
            q = text_filter.lower()
            result = [i for i in result if q in i["item_data"]["name"].lower()]
        if category_ids:
            ids = set(category_ids)
            result = [
                i
                for i in result
                if any(c["id"] in ids for c in i["item_data"].get("categories", []))
            ]
        return result
