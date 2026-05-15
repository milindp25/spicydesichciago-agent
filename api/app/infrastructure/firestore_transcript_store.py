"""FirestoreTranscriptStore — read/write /calls/{sid}/transcript/full.

One doc per call (not a subcollection of turns) because transcripts are
read together and a typical call fits comfortably under the 1 MB doc
limit. One write at hangup is cheaper than N appends.
"""
from __future__ import annotations

from datetime import datetime

from google.cloud import firestore

from app.domain.transcript import Transcript, Turn

CALLS_COLLECTION = "calls"
TRANSCRIPT_SUBCOLLECTION = "transcript"
TRANSCRIPT_DOC_ID = "full"


class FirestoreTranscriptStore:
    def __init__(self, *, client: firestore.Client) -> None:
        self._db = client

    def _doc_ref(self, call_sid: str) -> firestore.DocumentReference:
        return (
            self._db.collection(CALLS_COLLECTION)
            .document(call_sid)
            .collection(TRANSCRIPT_SUBCOLLECTION)
            .document(TRANSCRIPT_DOC_ID)
        )

    def set(self, *, call_sid: str, turns: list[Turn], stored_at: datetime) -> None:
        """Overwrite the transcript doc for this call. Idempotent."""
        transcript = Transcript(call_sid=call_sid, stored_at=stored_at, turns=turns)
        self._doc_ref(call_sid).set(transcript.to_firestore())

    def get(self, call_sid: str) -> Transcript | None:
        snap = self._doc_ref(call_sid).get()
        if not snap.exists:
            return None
        return Transcript.from_firestore(call_sid=call_sid, data=snap.to_dict() or {})
