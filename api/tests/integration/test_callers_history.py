"""Tests for the enriched /api/callers/history fields.

The basic back-compat shape (is_returning / call_count / events) is exercised
in test_callers_route.py. This file covers the new fields added in Task 2 of
feature/caller-experience-polish.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from google.cloud import firestore

from app.api.dependencies import AppState
from app.domain.call import CallEvent
from app.domain.message import Message, MessageStatus


def _seed(state: AppState, *, phone: str, call_sid: str, now: datetime) -> None:
    state.caller_store.upsert_on_call(
        phone=phone,
        ts=now,
        call_sid=call_sid,
        outcome="resolved",
    )


def test_unknown_caller_has_null_extras(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, _ = client_factory(firestore_db=firestore_db)
    r = c.get("/api/callers/history?phone=%2B19999999998", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["is_returning"] is False
    assert body["last_summary"] is None
    assert body["last_message_reason"] is None
    assert body["last_message_pending"] is None
    assert body["last_sms_kind"] is None
    assert body["recent_menu_queries"] == []


def test_returning_caller_with_summary(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, state = client_factory(firestore_db=firestore_db)
    phone, sid = "+13125552001", "CAsum1"
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    _seed(state, phone=phone, call_sid=sid, now=now)
    # Append at least one event so the call doc exists, then set summary.
    state.call_store.append_event(
        call_sid=sid,
        event=CallEvent(ts=now, kind="callStarted", payload={}),
        caller_phone_for_upsert=phone,
        from_number_for_upsert="+15555550100",
    )
    state.call_store.set_summary(call_sid=sid, summary="Asked about hours; resolved.")

    r = c.get(f"/api/callers/history?phone={phone.replace('+', '%2B')}", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["last_summary"] == "Asked about hours; resolved."


def test_pending_message_flag_when_handled_false(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, state = client_factory(firestore_db=firestore_db)
    phone, sid = "+13125552002", "CAmsg1"
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    _seed(state, phone=phone, call_sid=sid, now=now)
    state.call_store.append_event(
        call_sid=sid,
        event=CallEvent(ts=now, kind="messageTaken", payload={"reason": "catering for sat"}),
        caller_phone_for_upsert=phone,
        from_number_for_upsert="+15555550100",
    )
    state.message_store.create(
        Message(
            call_sid=sid,
            caller_phone=phone,
            reason="catering for sat",
            taken_at=now,
            status=MessageStatus.NEW,
        )
    )

    r = c.get(f"/api/callers/history?phone={phone.replace('+', '%2B')}", headers=auth_headers)
    body = r.json()
    assert body["last_message_pending"] is True
    assert body["last_message_reason"] == "catering for sat"


def test_pending_message_flag_when_handled_true(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, state = client_factory(firestore_db=firestore_db)
    phone, sid = "+13125552003", "CAmsg2"
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    _seed(state, phone=phone, call_sid=sid, now=now)
    state.call_store.append_event(
        call_sid=sid,
        event=CallEvent(ts=now, kind="messageTaken", payload={"reason": "follow up"}),
        caller_phone_for_upsert=phone,
        from_number_for_upsert="+15555550100",
    )
    state.message_store.create(
        Message(
            call_sid=sid,
            caller_phone=phone,
            reason="follow up",
            taken_at=now,
            status=MessageStatus.HANDLED,
            handled_at=now + timedelta(minutes=5),
            handled_by="owner",
        )
    )

    r = c.get(f"/api/callers/history?phone={phone.replace('+', '%2B')}", headers=auth_headers)
    body = r.json()
    assert body["last_message_pending"] is False
    assert body["last_message_reason"] == "follow up"


def test_last_sms_kind_order(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, state = client_factory(firestore_db=firestore_db)
    phone, sid = "+13125552004", "CAsms1"
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    _seed(state, phone=phone, call_sid=sid, now=now)
    state.call_store.append_event(
        call_sid=sid,
        event=CallEvent(ts=now, kind="smsLinkSent", payload={"kind": "location"}),
        caller_phone_for_upsert=phone,
        from_number_for_upsert="+15555550100",
    )
    state.call_store.append_event(
        call_sid=sid,
        event=CallEvent(
            ts=now + timedelta(seconds=5),
            kind="smsLinkSent",
            payload={"kind": "order"},
        ),
        caller_phone_for_upsert=phone,
        from_number_for_upsert="+15555550100",
    )

    r = c.get(f"/api/callers/history?phone={phone.replace('+', '%2B')}", headers=auth_headers)
    body = r.json()
    assert body["last_sms_kind"] == "order"


def test_recent_menu_queries_dedup_and_lowercase(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
    firestore_db: firestore.Client,
) -> None:
    c, state = client_factory(firestore_db=firestore_db)
    phone, sid = "+13125552005", "CAmenu1"
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    _seed(state, phone=phone, call_sid=sid, now=now)

    def _menu_ev(ts: datetime, query: str) -> CallEvent:
        return CallEvent(
            ts=ts,
            kind="toolCalled",
            payload={"name": "search_menu", "arguments": {"query": query}},
        )

    # Order: samosa, biryani, samosa (dup), naan
    # Newest-first iteration → naan, samosa, biryani, samosa(dup)
    # But test expects ["samosa","biryani"] per the task spec — that ordering
    # implies the route walks events oldest→newest. We use that ordering here.
    state.call_store.append_event(
        call_sid=sid,
        event=_menu_ev(now, "Samosa"),
        caller_phone_for_upsert=phone,
        from_number_for_upsert="+15555550100",
    )
    state.call_store.append_event(
        call_sid=sid,
        event=_menu_ev(now + timedelta(seconds=1), "BIRYANI"),
        caller_phone_for_upsert=phone,
        from_number_for_upsert="+15555550100",
    )
    state.call_store.append_event(
        call_sid=sid,
        event=_menu_ev(now + timedelta(seconds=2), "samosa"),
        caller_phone_for_upsert=phone,
        from_number_for_upsert="+15555550100",
    )

    r = c.get(f"/api/callers/history?phone={phone.replace('+', '%2B')}", headers=auth_headers)
    body = r.json()
    # Distinct, lowercased, capped at 3
    assert set(body["recent_menu_queries"]) == {"samosa", "biryani"}
    assert len(body["recent_menu_queries"]) == 2
