from collections.abc import Callable

from fastapi.testclient import TestClient

from app.api.dependencies import AppState


def test_metrics_aggregates_events(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _state = client_factory()
    # Plant a small mix of events via the existing /events route.
    for kind, sid in [
        ("call_started", "CA1"),
        ("tool_error", "CA1"),
        ("call_ended", "CA1"),
        ("call_started", "CA2"),
    ]:
        c.post(
            f"/api/calls/{sid}/event",
            headers=auth_headers,
            json={"kind": kind, "payload": {}},
        )

    r = c.get("/api/metrics", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_events"] >= 4
    assert body["events_by_kind"].get("tool_error") == 1
    assert body["unique_calls"] >= 2


def test_metrics_requires_auth(
    client_factory: Callable[..., tuple[TestClient, AppState]],
) -> None:
    c, _ = client_factory()
    r = c.get("/api/metrics")
    assert r.status_code == 401
