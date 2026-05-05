from collections.abc import Callable

from fastapi.testclient import TestClient

from app.api.dependencies import AppState


def test_cors_preflight_allowed_origin(
    client_factory: Callable[..., tuple[TestClient, AppState]],
) -> None:
    c, _ = client_factory(cors_origins=["https://admin.example.com"])
    r = c.options(
        "/api/specials",
        headers={
            "Origin": "https://admin.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "https://admin.example.com"


def test_cors_disabled_when_no_origins_configured(
    client_factory: Callable[..., tuple[TestClient, AppState]],
) -> None:
    c, _ = client_factory(cors_origins=[])
    r = c.options(
        "/api/specials",
        headers={
            "Origin": "https://admin.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Without CORS middleware, the OPTIONS preflight is not handled and
    # no allow-origin header is returned.
    assert "access-control-allow-origin" not in r.headers
