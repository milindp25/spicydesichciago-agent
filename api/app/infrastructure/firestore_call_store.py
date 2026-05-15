"""FirestoreCallStore — read/write /calls and /calls/{sid}/events.

camelCase on the wire; snake_case in Python. Translation happens in
the Call / CallEvent models (to_firestore / from_firestore).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterator

from google.cloud import firestore

from app.domain.call import Call, CallEvent, Outcome

CALLS_COLLECTION = "calls"
EVENTS_SUBCOLLECTION = "events"


class FirestoreCallStore:
    def __init__(self, *, client: firestore.Client) -> None:
        self._db = client

    def _call_ref(self, call_sid: str) -> firestore.DocumentReference:
        return self._db.collection(CALLS_COLLECTION).document(call_sid)

    def record_call_start(self, call: Call) -> None:
        """Create or update the call doc. Idempotent — merges with existing."""
        self._call_ref(call.call_sid).set(call.to_firestore(), merge=True)

    def record_call_end(
        self,
        *,
        call_sid: str,
        ended_at: datetime,
        outcome: Outcome,
        duration_ms: int | None,
    ) -> None:
        self._call_ref(call_sid).set(
            {
                "endedAt": ended_at,
                "outcome": outcome.value,
                "durationMs": duration_ms,
            },
            merge=True,
        )

    def set_summary(self, *, call_sid: str, summary: str) -> None:
        self._call_ref(call_sid).set({"summary": summary}, merge=True)

    def get_call(self, call_sid: str) -> Call | None:
        snap = self._call_ref(call_sid).get()
        if not snap.exists:
            return None
        return Call.from_firestore(call_sid=call_sid, data=snap.to_dict() or {})

    def append_event(
        self,
        *,
        call_sid: str,
        event: CallEvent,
        caller_phone_for_upsert: str,
        from_number_for_upsert: str,
    ) -> None:
        """Append a sub-event. If the parent /calls/{sid} doc doesn't exist,
        create it with minimum required fields so foreign-key-ish reads work.

        We use set(..., merge=True) on the parent so existing fields are
        preserved when the doc already exists.
        """
        call_ref = self._call_ref(call_sid)
        snap = call_ref.get()
        if not snap.exists:
            call_ref.set(
                {
                    "startedAt": event.ts,
                    "callerPhone": caller_phone_for_upsert,
                    "fromNumber": from_number_for_upsert,
                    "outcome": Outcome.IN_PROGRESS.value,
                    "toolsUsed": [],
                },
                merge=True,
            )
        call_ref.collection(EVENTS_SUBCOLLECTION).add(event.to_firestore())

    def list_in_window(
        self, *, start_utc: datetime, end_utc: datetime, limit: int = 1000
    ) -> list[Call]:
        """Return calls whose startedAt is within [start_utc, end_utc).

        Used by the daily-stats materializer. Day boundaries are expected to
        be computed by the caller in the target timezone, then converted to
        UTC for the Firestore query.
        """
        query = (
            self._db.collection(CALLS_COLLECTION)
            .where(filter=firestore.FieldFilter("startedAt", ">=", start_utc))
            .where(filter=firestore.FieldFilter("startedAt", "<", end_utc))
            .limit(limit)
        )
        return [
            Call.from_firestore(call_sid=snap.id, data=snap.to_dict() or {})
            for snap in query.stream()
        ]

    def list_today_chicago(self, *, limit: int = 200) -> Iterator[tuple[str, Call]]:
        """List calls whose startedAt is within today's date in America/Chicago.

        Computes the day boundary in Chicago time and queries Firestore on
        a UTC range. Yields (call_sid, Call) tuples ordered newest first.
        """
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        chi = ZoneInfo("America/Chicago")
        now_chi = datetime.now(chi)
        start_chi = now_chi.replace(hour=0, minute=0, second=0, microsecond=0)
        end_chi = start_chi + timedelta(days=1)
        start_utc = start_chi.astimezone(ZoneInfo("UTC"))
        end_utc = end_chi.astimezone(ZoneInfo("UTC"))

        query = (
            self._db.collection(CALLS_COLLECTION)
            .where(filter=firestore.FieldFilter("startedAt", ">=", start_utc))
            .where(filter=firestore.FieldFilter("startedAt", "<", end_utc))
            .order_by("startedAt", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        for snap in query.stream():
            yield snap.id, Call.from_firestore(call_sid=snap.id, data=snap.to_dict() or {})

    def iter_events(self, call_sid: str) -> Iterator[CallEvent]:
        for snap in (
            self._call_ref(call_sid)
            .collection(EVENTS_SUBCOLLECTION)
            .order_by("ts")
            .stream()
        ):
            data = snap.to_dict() or {}
            yield CallEvent.from_firestore(data)
