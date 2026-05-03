from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/menu/search")
async def search_menu(
    request: Request,
    tenant: str = Query(..., min_length=1),
    q: str = Query(..., min_length=1),
) -> dict[str, Any]:
    state = get_state(request)
    if tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    items = await state.catalog_service.search_menu(q)
    return {"items": [i.model_dump() for i in items]}


@router.get("/menu/list")
async def list_menu(
    request: Request,
    tenant: str = Query(..., min_length=1),
    category: str | None = Query(None),
) -> dict[str, Any]:
    """Return all items, or only items in a given category (case-insensitive).

    Each item is trimmed to {name, price, category} to keep the LLM
    context window small.
    """
    state = get_state(request)
    if tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    items = await state.catalog_service.list_all_menu()
    if category:
        cat_lower = category.lower().strip()
        items = [i for i in items if (i.category or "").lower().strip() == cat_lower]
    return {
        "items": [
            {"name": i.name, "price": i.price, "category": i.category} for i in items
        ]
    }


@router.get("/menu/categories")
async def list_menu_categories(
    request: Request,
    tenant: str = Query(..., min_length=1),
) -> dict[str, Any]:
    """Return just the category names with counts. Compact, low-token."""
    state = get_state(request)
    if tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    items = await state.catalog_service.list_all_menu()
    counts: dict[str, int] = {}
    for item in items:
        cat = (item.category or "Uncategorized").strip()
        counts[cat] = counts.get(cat, 0) + 1
    return {
        "categories": [
            {"name": name, "count": count}
            for name, count in sorted(counts.items(), key=lambda kv: -kv[1])
        ]
    }
