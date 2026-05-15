"""FirestoreMessageStore — read/write /messages."""
from __future__ import annotations

from datetime import datetime
from typing import Iterator

from google.cloud import firestore

from app.domain.message import Message, MessageStatus

MESSAGES_COLLECTION = "messages"


class FirestoreMessageStore:
    def __init__(self, *, client: firestore.Client) -> None:
        self._db = client

    def create(self, message: Message) -> str:
        _, ref = self._db.collection(MESSAGES_COLLECTION).add(message.to_firestore())
        return ref.id

    def get(self, message_id: str) -> Message | None:
        snap = self._db.collection(MESSAGES_COLLECTION).document(message_id).get()
        if not snap.exists:
            return None
        return Message.from_firestore(data=snap.to_dict() or {})

    def list_unhandled(self, *, limit: int = 50) -> Iterator[Message]:
        query = (
            self._db.collection(MESSAGES_COLLECTION)
            .where(filter=firestore.FieldFilter("status", "==", MessageStatus.NEW.value))
            .order_by("takenAt", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        for snap in query.stream():
            yield Message.from_firestore(data=snap.to_dict() or {})

    def mark_handled(
        self,
        *,
        message_id: str,
        handled_at: datetime,
        handled_by: str,
    ) -> None:
        self._db.collection(MESSAGES_COLLECTION).document(message_id).set(
            {
                "status": MessageStatus.HANDLED.value,
                "handledAt": handled_at,
                "handledBy": handled_by,
            },
            merge=True,
        )
