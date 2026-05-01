from __future__ import annotations

from typing import Any, Protocol

from square import AsyncSquare
from square.environment import SquareEnvironment


class LocationsApi(Protocol):
    async def list_locations(self) -> list[dict[str, Any]]: ...
    async def retrieve_location(self, location_id: str) -> dict[str, Any] | None: ...


class CatalogApi(Protocol):
    async def search_items(
        self,
        *,
        text_filter: str | None = None,
        category_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...


def make_square_client(*, access_token: str, environment: str) -> AsyncSquare:
    env = (
        SquareEnvironment.PRODUCTION
        if environment == "production"
        else SquareEnvironment.SANDBOX
    )
    return AsyncSquare(token=access_token, environment=env)


def _model_to_dict(obj: Any) -> dict[str, Any]:
    """Convert a Pydantic model from the Square SDK into a plain dict the rest of the
    app can work with (decouples services from SDK types)."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()  # type: ignore[no-any-return]
    if isinstance(obj, dict):
        return obj
    raise TypeError(f"cannot convert {type(obj).__name__} to dict")


class SquareLocationsAdapter:
    def __init__(self, client: AsyncSquare) -> None:
        self._client = client

    async def list_locations(self) -> list[dict[str, Any]]:
        response = await self._client.locations.list()
        return [_model_to_dict(loc) for loc in (response.locations or [])]

    async def retrieve_location(self, location_id: str) -> dict[str, Any] | None:
        try:
            response = await self._client.locations.get(location_id)
        except Exception:
            return None
        return _model_to_dict(response.location) if response.location else None


class SquareCatalogAdapter:
    def __init__(self, client: AsyncSquare) -> None:
        self._client = client

    async def search_items(
        self,
        *,
        text_filter: str | None = None,
        category_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {}
        if text_filter is not None:
            kwargs["text_filter"] = text_filter
        if category_ids is not None:
            kwargs["category_ids"] = category_ids
        response = await self._client.catalog.search_items(**kwargs)
        return [_model_to_dict(item) for item in (response.items or [])]
