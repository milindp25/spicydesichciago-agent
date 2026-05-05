from collections.abc import Callable

from fastapi.testclient import TestClient

from app.api.dependencies import AppState


def test_tenant_returns_greeting_and_owner_available(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory()
    r = c.get("/api/tenant?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "spicy-desi"
    assert body["name"] == "Spicy Desi"
    assert "owner_available" in body
    assert isinstance(body["owner_available"], bool)


def test_tenant_unknown_404(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory()
    r = c.get("/api/tenant?tenant=nope", headers=auth_headers)
    assert r.status_code == 404


def test_tenant_requires_auth(
    client_factory: Callable[..., tuple[TestClient, AppState]],
) -> None:
    c, _ = client_factory()
    r = c.get("/api/tenant?tenant=spicy-desi")
    assert r.status_code == 401
