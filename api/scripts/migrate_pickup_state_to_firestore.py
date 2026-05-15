"""One-shot migration: ./data/pickup-state.json -> Firestore /pickupState/{slug}.

Idempotent — re-running overwrites cleanly.

Usage:
    python -m scripts.migrate_pickup_state_to_firestore [--path PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.domain.pickup import PickupRecord
from app.infrastructure.config import AppSettings
from app.infrastructure.firestore_client import FirestoreClient
from app.infrastructure.firestore_pickup_state_store import FirestorePickupStateStore


def _load(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"pickup-state file not found: {path}")
    raw = path.read_text() or "{}"
    return json.loads(raw)


def main(path: str = "./data/pickup-state.json", dry_run: bool = False) -> int:
    p = Path(path)
    try:
        data = _load(p)
    except Exception as e:
        print(f"ERROR loading {p}: {e}", file=sys.stderr)
        return 1

    if not data:
        print(f"No entries in {p}; nothing to migrate.")
        return 0

    store: FirestorePickupStateStore | None = None
    if not dry_run:
        settings = AppSettings()
        db = FirestoreClient(
            project_id=settings.firebase_project_id,
            service_account_path=settings.firebase_service_account_path,
        ).db
        store = FirestorePickupStateStore(client=db)

    failures = 0
    for tenant_slug, entry in data.items():
        try:
            record = PickupRecord.from_firestore(
                {
                    "locationId": entry["location_id"],
                    "setAt": entry["set_at"],
                    "setForDate": entry["set_for_date"],
                }
            )
        except Exception as e:
            print(f"  [skip] {tenant_slug}: invalid entry ({e})", file=sys.stderr)
            failures += 1
            continue

        if dry_run:
            print(f"  [dry-run] would write pickupState/{tenant_slug} = {record.to_firestore()}")
            continue

        assert store is not None
        try:
            store.set(tenant_slug, record)
            print(f"  [ok] wrote pickupState/{tenant_slug}")
        except Exception as e:
            print(f"  [fail] {tenant_slug}: {e}", file=sys.stderr)
            failures += 1

    return 1 if failures else 0


def _cli() -> int:
    parser = argparse.ArgumentParser(prog="migrate_pickup_state_to_firestore")
    parser.add_argument("--path", default="./data/pickup-state.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return main(path=args.path, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(_cli())
