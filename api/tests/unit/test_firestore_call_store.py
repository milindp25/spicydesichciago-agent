"""Tests for FirestoreCallStore against the emulator."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.call import Call, CallEvent, Outcome
from app.infrastructure.firestore_call_store import FirestoreCallStore


@pytest.fixture
def store(firestore_db):
    return FirestoreCallStore(client=firestore_db)


def test_record_call_start_creates_doc(store):
    call = Call(
        call_sid="CA1",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    store.record_call_start(call)

    fetched = store.get_call("CA1")
    assert fetched is not None
    assert fetched.call_sid == "CA1"
    assert fetched.outcome == Outcome.IN_PROGRESS


def test_record_call_start_is_idempotent_via_merge(store):
    """Calling record_call_start twice with same call_sid doesn't lose fields
    added by record_call_end (e.g., endedAt set before re-start)."""
    started_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    call = Call(
        call_sid="CA1",
        started_at=started_at,
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    store.record_call_start(call)
    store.record_call_start(call)  # second call

    fetched = store.get_call("CA1")
    assert fetched is not None
    assert fetched.started_at == started_at


def test_record_call_end_sets_ended_and_duration(store):
    call = Call(
        call_sid="CA1",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    store.record_call_start(call)
    ended_at = datetime(2026, 5, 14, 12, 1, 30, tzinfo=timezone.utc)
    store.record_call_end(
        call_sid="CA1",
        ended_at=ended_at,
        outcome=Outcome.RESOLVED,
        duration_ms=90_000,
    )

    fetched = store.get_call("CA1")
    assert fetched is not None
    assert fetched.ended_at == ended_at
    assert fetched.outcome == Outcome.RESOLVED
    assert fetched.duration_ms == 90_000


def test_set_summary(store):
    call = Call(
        call_sid="CA1",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    store.record_call_start(call)
    store.set_summary(call_sid="CA1", summary="Asked about hours and momos")
    fetched = store.get_call("CA1")
    assert fetched is not None
    assert fetched.summary == "Asked about hours and momos"


def test_append_event_creates_call_if_missing(store):
    """append_event upserts the parent call doc with the minimum required
    fields if the call wasn't pre-recorded — preserves event-only writes
    from the existing agent's POST /api/calls/{sid}/event flow."""
    ev = CallEvent(
        ts=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
        kind="toolCalled",
        payload={"tool": "listMenuCategories"},
    )
    store.append_event(
        call_sid="CA-new",
        event=ev,
        caller_phone_for_upsert="+15551234567",
        from_number_for_upsert="+15559998888",
    )
    fetched = store.get_call("CA-new")
    assert fetched is not None
    assert fetched.caller_phone == "+15551234567"
    events = list(store.iter_events("CA-new"))
    assert len(events) == 1
    assert events[0].kind == "toolCalled"


def test_append_event_does_not_clobber_existing_call(store):
    """If the call doc already exists, append_event must not overwrite its
    fields with the upsert defaults."""
    started_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    call = Call(
        call_sid="CA1",
        started_at=started_at,
        caller_phone="+15551234567",
        from_number="+15559998888",
        tools_used=["listMenuCategories"],
    )
    store.record_call_start(call)
    ev = CallEvent(
        ts=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
        kind="transferInitiated",
    )
    store.append_event(
        call_sid="CA1",
        event=ev,
        caller_phone_for_upsert="+19998887777",  # WRONG on purpose — must be ignored
        from_number_for_upsert="+10000000000",
    )
    fetched = store.get_call("CA1")
    assert fetched is not None
    assert fetched.caller_phone == "+15551234567"
    assert fetched.tools_used == ["listMenuCategories"]


def test_get_call_returns_none_when_missing(store):
    assert store.get_call("CA-missing") is None


def test_iter_events_orders_by_ts(store):
    call = Call(
        call_sid="CA1",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    store.record_call_start(call)

    second = CallEvent(ts=datetime(2026, 5, 14, 12, 2, tzinfo=timezone.utc), kind="b")
    first = CallEvent(ts=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc), kind="a")
    store.append_event(
        call_sid="CA1",
        event=second,
        caller_phone_for_upsert="+15551234567",
        from_number_for_upsert="+15559998888",
    )
    store.append_event(
        call_sid="CA1",
        event=first,
        caller_phone_for_upsert="+15551234567",
        from_number_for_upsert="+15559998888",
    )

    kinds = [e.kind for e in store.iter_events("CA1")]
    assert kinds == ["a", "b"]


def test_list_today_chicago_returns_todays_calls_only(store):
    """Seed three calls: yesterday, today-early, today-late.
    Expect only today's two, newest first.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    chi = ZoneInfo("America/Chicago")
    today_chi = datetime.now(chi).replace(hour=9, minute=0, second=0, microsecond=0)
    yesterday_chi = today_chi - timedelta(days=1)
    today_later_chi = today_chi + timedelta(hours=5)

    for sid, ts in (
        ("CA-yesterday", yesterday_chi),
        ("CA-today-early", today_chi),
        ("CA-today-late", today_later_chi),
    ):
        store.record_call_start(Call(
            call_sid=sid,
            started_at=ts,
            caller_phone="+15551234567",
            from_number="+15559998888",
        ))

    todays = list(store.list_today_chicago(limit=50))
    sids = [s for s, _ in todays]
    assert "CA-yesterday" not in sids
    assert sids == ["CA-today-late", "CA-today-early"]
