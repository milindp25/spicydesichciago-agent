"""FirestoreOwnerOverrideStore — singleton /ownerOverride/current."""
from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore

from app.domain.owner_override import OwnerOverride

COLLECTION = "ownerOverride"
DOC_ID = "current"


class FirestoreOwnerOverrideStore:
    def __init__(self, *, client: firestore.Client) -> None:
        self._db = client

    def _ref(self) -> firestore.DocumentReference:
        return self._db.collection(COLLECTION).document(DOC_ID)

    def get_current(self) -> OwnerOverride | None:
        snap = self._ref().get()
        if not snap.exists:
            return None
        return OwnerOverride.from_firestore(snap.to_dict() or {})

    def set(self, override: OwnerOverride) -> None:
        self._ref().set(override.to_firestore())

    def clear(self, *, cleared_by: str) -> None:
        self._ref().set(
            OwnerOverride(
                active=False,
                until_iso=None,
                reason=None,
                set_by=cleared_by,
                set_at=datetime.now(timezone.utc),
            ).to_firestore()
        )
