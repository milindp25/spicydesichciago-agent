"""FirestoreCallerStore — read/write /callers/{e164}."""
from __future__ import annotations

from datetime import datetime

from google.cloud import firestore

from app.domain.caller import Caller

CALLERS_COLLECTION = "callers"


class FirestoreCallerStore:
    def __init__(self, *, client: firestore.Client) -> None:
        self._db = client

    def _ref(self, phone: str) -> firestore.DocumentReference:
        return self._db.collection(CALLERS_COLLECTION).document(phone)

    def get(self, phone: str) -> Caller | None:
        snap = self._ref(phone).get()
        if not snap.exists:
            return None
        return Caller.from_firestore(phone=phone, data=snap.to_dict() or {})

    def upsert_on_call(
        self,
        *,
        phone: str,
        ts: datetime,
        call_sid: str,
        outcome: str,
    ) -> None:
        """Upsert a caller record on every call. First call sets firstSeen
        and callCount=1; subsequent calls update lastSeen, increment callCount,
        and refresh lastCallSid + lastOutcome. firstSeen is preserved."""
        ref = self._ref(phone)
        self._transactional_upsert(ref, ts=ts, call_sid=call_sid, outcome=outcome)

    @staticmethod
    @firestore.transactional
    def _txn_upsert(
        transaction: firestore.Transaction,
        ref: firestore.DocumentReference,
        ts: datetime,
        call_sid: str,
        outcome: str,
    ) -> None:
        snap = ref.get(transaction=transaction)
        if snap.exists:
            data = snap.to_dict() or {}
            transaction.update(
                ref,
                {
                    "lastSeen": ts,
                    "callCount": (data.get("callCount", 0) or 0) + 1,
                    "lastCallSid": call_sid,
                    "lastOutcome": outcome,
                },
            )
        else:
            transaction.set(
                ref,
                {
                    "firstSeen": ts,
                    "lastSeen": ts,
                    "callCount": 1,
                    "lastCallSid": call_sid,
                    "lastOutcome": outcome,
                    "notes": "",
                },
            )

    def _transactional_upsert(
        self,
        ref: firestore.DocumentReference,
        *,
        ts: datetime,
        call_sid: str,
        outcome: str,
    ) -> None:
        transaction = self._db.transaction()
        self._txn_upsert(transaction, ref, ts, call_sid, outcome)
