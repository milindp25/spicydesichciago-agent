from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from google.cloud import firestore

from app.api.dependencies import AppState

LOC: list[dict[str, Any]] = [
    {
        "id": "L1",
        "name": "29th Street Near PS",
        "address": {
            "address_line1": "29th & Halsted",
            "locality": "Chicago",
            "administrative_district_level1": "IL",
            "postal_code": "60619",
        },
        "business_hours": {
            "periods": [
                {"day_of_week": "MON", "start_local_time": "11:00:00", "end_local_time": "21:30:00"}
            ]
        },
    }
]


def _set_pickup(c: TestClient, headers: dict[str, str]) -> None:
    c.post(
        "/api/admin/pickup",
        headers=headers,
        json={"tenant": "spicy-desi", "location_id": "L1"},
    )


def test_send_order_link_sms(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, state = client_factory(locations=LOC, firestore_db=firestore_db)
    r = c.post(
        "/api/sms/send-link",
        headers=auth_headers,
        json={"call_sid": "CA1", "to": "+13125551111", "kind": "order"},
    )
    assert r.status_code == 202
    assert state.twilio.sms_calls[0]["to"] == "+13125551111"
    assert "order.spicydesi.com" in state.twilio.sms_calls[0]["body"]

    # Firestore: smsLinkSent event written under /calls/CA1/events.
    events = list(state.call_store.iter_events("CA1"))
    assert len(events) == 1
    assert events[0].kind == "smsLinkSent"
    assert events[0].payload["kind"] == "order"
    assert events[0].payload["to"] == "+13125551111"
    assert events[0].payload["sms_sent"] is True


def test_send_location_link_sms(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, state = client_factory(locations=LOC)
    _set_pickup(c, auth_headers)
    r = c.post(
        "/api/sms/send-link",
        headers=auth_headers,
        json={"call_sid": "CA1", "to": "+13125551111", "kind": "location"},
    )
    assert r.status_code == 202
    body = state.twilio.sms_calls[0]["body"]
    assert "29th & Halsted" in body
    assert "google.com/maps" in body


def test_location_link_409_when_no_pickup_set(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, _ = client_factory(locations=LOC)
    r = c.post(
        "/api/sms/send-link",
        headers=auth_headers,
        json={"call_sid": "CA1", "to": "+13125551111", "kind": "location"},
    )
    assert r.status_code == 409
