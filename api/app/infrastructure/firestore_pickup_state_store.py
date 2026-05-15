"""FirestorePickupStateStore — per-tenant active pickup record at pickupState/{slug}."""
from __future__ import annotations

from google.cloud import firestore

from app.domain.pickup import PickupRecord

COLLECTION = "pickupState"


class FirestorePickupStateStore:
    def __init__(self, *, client: firestore.Client) -> None:
        self._db = client

    def _ref(self, tenant_slug: str) -> firestore.DocumentReference:
        return self._db.collection(COLLECTION).document(tenant_slug)

    def get(self, tenant_slug: str) -> PickupRecord | None:
        snap = self._ref(tenant_slug).get()
        if not snap.exists:
            return None
        return PickupRecord.from_firestore(snap.to_dict() or {})

    def set(self, tenant_slug: str, record: PickupRecord) -> None:
        self._ref(tenant_slug).set(record.to_firestore())
