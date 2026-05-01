from collections.abc import Callable

from fastapi.testclient import TestClient

from app.api.dependencies import AppState
from app.domain.models import MenuItem


def test_returns_specials_from_tenant_config(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, state = client_factory()
    state.tenants.tenants["spicy-desi"].specials.append(
        MenuItem(
            name="Mango Lassi",
            description="sweet yogurt drink",
            price="$4.99",
            category="Drinks",
            dietary_tags=["vegetarian"],
        )
    )
    r = c.get("/api/specials?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["items"][0]["name"] == "Mango Lassi"


def test_empty_specials_returns_empty_list(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory()
    r = c.get("/api/specials?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_unknown_tenant_returns_404(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory()
    r = c.get("/api/specials?tenant=nope", headers=auth_headers)
    assert r.status_code == 404
