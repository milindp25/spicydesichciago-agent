"""Firestore client initialization with three credential paths:

1. Emulator: if FIRESTORE_EMULATOR_HOST env is set, google-cloud-firestore
   auto-detects it and never touches real Firebase. We pass through.
2. Explicit service-account JSON: when service_account_path is non-empty,
   we load credentials from that file. Used on hosts that don't provide
   ambient credentials (Fly, Hetzner).
3. Ambient: when service_account_path is empty AND no emulator host,
   google-auth attempts metadata-server / GOOGLE_APPLICATION_CREDENTIALS.
   Works automatically on Cloud Run.

The client is created lazily on first .db access and cached.
"""
from __future__ import annotations

from google.cloud import firestore
from google.oauth2 import service_account


class FirestoreClient:
    def __init__(self, *, project_id: str, service_account_path: str) -> None:
        self._project_id = project_id
        self._service_account_path = service_account_path
        self._client: firestore.Client | None = None

    @property
    def db(self) -> firestore.Client:
        if self._client is None:
            if self._service_account_path:
                creds = service_account.Credentials.from_service_account_file(
                    self._service_account_path
                )
                self._client = firestore.Client(project=self._project_id, credentials=creds)
            else:
                self._client = firestore.Client(project=self._project_id)
        return self._client
