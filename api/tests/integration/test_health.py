from fastapi.testclient import TestClient


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_healthz_does_not_require_auth(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
