"""Tests for the one-shot pickup-state JSON -> Firestore migration."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from app.infrastructure.firestore_pickup_state_store import FirestorePickupStateStore
from scripts import migrate_pickup_state_to_firestore as migrate


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_migration_writes_each_tenant_to_firestore(tmp_path: Path, firestore_db) -> None:
    json_path = tmp_path / "pickup-state.json"
    _write_json(
        json_path,
        {
            "spicy-desi": {
                "location_id": "L1",
                "set_at": "2026-05-15T12:00:00+00:00",
                "set_for_date": "2026-05-15",
            },
            "other-tenant": {
                "location_id": "L9",
                "set_at": "2026-05-14T10:00:00Z",
                "set_for_date": "2026-05-14",
            },
        },
    )

    store = FirestorePickupStateStore(client=firestore_db)
    with patch.object(migrate, "FirestoreClient") as fc, patch.object(
        migrate, "AppSettings"
    ) as settings_cls:
        fc.return_value.db = firestore_db
        settings_cls.return_value.firebase_project_id = "test"
        settings_cls.return_value.firebase_service_account_path = None
        rc = migrate.main(path=str(json_path), dry_run=False)

    assert rc == 0
    a = store.get("spicy-desi")
    assert a is not None
    assert a.location_id == "L1"
    assert a.set_for_date == "2026-05-15"
    b = store.get("other-tenant")
    assert b is not None
    assert b.location_id == "L9"


def test_migration_dry_run_does_not_write(tmp_path: Path, firestore_db) -> None:
    json_path = tmp_path / "pickup-state.json"
    _write_json(
        json_path,
        {
            "spicy-desi": {
                "location_id": "L1",
                "set_at": "2026-05-15T12:00:00+00:00",
                "set_for_date": "2026-05-15",
            }
        },
    )

    rc = migrate.main(path=str(json_path), dry_run=True)
    assert rc == 0

    store = FirestorePickupStateStore(client=firestore_db)
    assert store.get("spicy-desi") is None


def test_migration_missing_file_returns_1(tmp_path: Path) -> None:
    rc = migrate.main(path=str(tmp_path / "nope.json"), dry_run=True)
    assert rc == 1


def test_migration_empty_file_returns_0(tmp_path: Path) -> None:
    json_path = tmp_path / "pickup-state.json"
    json_path.write_text("{}")
    rc = migrate.main(path=str(json_path), dry_run=True)
    assert rc == 0


def test_migration_is_idempotent(tmp_path: Path, firestore_db) -> None:
    json_path = tmp_path / "pickup-state.json"
    _write_json(
        json_path,
        {
            "spicy-desi": {
                "location_id": "L1",
                "set_at": "2026-05-15T12:00:00+00:00",
                "set_for_date": "2026-05-15",
            }
        },
    )

    with patch.object(migrate, "FirestoreClient") as fc, patch.object(
        migrate, "AppSettings"
    ) as settings_cls:
        fc.return_value.db = firestore_db
        settings_cls.return_value.firebase_project_id = "test"
        settings_cls.return_value.firebase_service_account_path = None
        assert migrate.main(path=str(json_path), dry_run=False) == 0
        assert migrate.main(path=str(json_path), dry_run=False) == 0

    store = FirestorePickupStateStore(client=firestore_db)
    assert store.get("spicy-desi") is not None
