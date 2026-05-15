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

    def iter_events(self, call_sid: str) -> Iterator[CallEvent]:
        for snap in (
            self._call_ref(call_sid)
            .collection(EVENTS_SUBCOLLECTION)
            .order_by("ts")
            .stream()
        ):
            data = snap.to_dict() or {}
            yield CallEvent.from_firestore(data)
