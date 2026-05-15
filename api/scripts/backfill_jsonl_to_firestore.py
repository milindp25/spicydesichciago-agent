"""Backfill api/data/events.jsonl into Firestore.

Idempotent — safe to re-run with --clear. Reconstructs:
- /calls/{sid} from call_started + the rest
- /calls/{sid}/events/ subcollection
- /callers/{phone}
- /messages/{autoId} (for message_taken events that lack a primary record)

DATA-SAFETY GUARANTEES:
- This script only ever writes to OUR_COLLECTIONS = {"calls","callers","messages"}.
- The --clear flag refuses to delete any collection not in OUR_COLLECTIONS.
- Before doing any write, the script checks that the target collections
  do not contain dashboard-owned field names (e.g., "actorUid") — if they
  do, it aborts because that's a sign we're pointing at the wrong project.

Usage:
    FIREBASE_SERVICE_ACCOUNT_PATH=~/.config/spicy-desi/firebase-admin.json \\
    FIREBASE_PROJECT_ID=spicy-desi-chicago \\
    api/.venv/bin/python -m scripts.backfill_jsonl_to_firestore api/data/events.jsonl

Run from inside api/ so the module import works:
    cd api && \\
    FIREBASE_SERVICE_ACCOUNT_PATH=... .venv/bin/python -m scripts.backfill_jsonl_to_firestore data/events.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.domain.call import CallEvent
from app.domain.message import Message
from app.infrastructure.firestore_call_store import FirestoreCallStore
from app.infrastructure.firestore_caller_store import FirestoreCallerStore
from app.infrastructure.firestore_client import FirestoreClient
from app.infrastructure.firestore_message_store import FirestoreMessageStore

OUR_COLLECTIONS: frozenset[str] = frozenset({"calls", "callers", "messages"})
DASHBOARD_FIELD_FINGERPRINTS: frozenset[str] = frozenset(
    {"actorUid", "actorEmail", "squareItemId", "sortOrder", "minQty", "checklistTemplates"}
)


def _abort_if_collections_look_like_dashboard(db) -> None:
    """Sanity check: if any 'our' collection in the target project contains
    documents with dashboard field names, abort — we're pointed at the wrong
    project or someone else owns these paths."""
    for coll_name in OUR_COLLECTIONS:
        docs = list(db.collection(coll_name).limit(3).stream())
        for d in docs:
            data = d.to_dict() or {}
            hits = DASHBOARD_FIELD_FINGERPRINTS & set(data.keys())
            if hits:
                raise SystemExit(
                    f"REFUSING TO RUN: collection /{coll_name} contains dashboard-owned "
                    f"fields {sorted(hits)}. This script is not pointed at the right project."
                )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("jsonl_path", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete /calls, /callers, /messages first (DESTRUCTIVE)",
    )
    args = parser.parse_args(argv)

    if not args.jsonl_path.exists():
        print(f"No file at {args.jsonl_path} — nothing to backfill", file=sys.stderr)
        return 0

    client = FirestoreClient(
        project_id=os.environ.get("FIREBASE_PROJECT_ID", "spicy-desi-chicago"),
        service_account_path=os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", ""),
    )

    # Safety: refuse to proceed if our target collections contain
    # dashboard-owned data (means we're pointed at the wrong project,
    # or someone else writes to these paths).
    _abort_if_collections_look_like_dashboard(client.db)

    if args.clear and not args.dry_run:
        # Hardcoded list — we iterate OUR_COLLECTIONS so this CAN'T be
        # parameterized to a dashboard-owned collection name by accident.
        for coll in OUR_COLLECTIONS:
            docs = list(client.db.collection(coll).limit(500).stream())
            while docs:
                batch = client.db.batch()
                for doc in docs:
                    batch.delete(doc.reference)
                batch.commit()
                docs = list(client.db.collection(coll).limit(500).stream())

    call_store = FirestoreCallStore(client=client.db)
    caller_store = FirestoreCallerStore(client=client.db)
    msg_store = FirestoreMessageStore(client=client.db)

    seen_calls: set[str] = set()
    seen_phones: set[str] = set()
    msg_count = 0
    event_count = 0

    with args.jsonl_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            call_sid = ev.get("call_sid") or ""
            kind = ev.get("kind") or ""
            payload = ev.get("payload") or {}
            ts_float = ev.get("ts")
            ts = (
                datetime.fromtimestamp(ts_float, tz=timezone.utc)
                if ts_float
                else datetime.now(timezone.utc)
            )
            caller_phone = (
                payload.get("from_phone")
                or payload.get("callback_number")
                or ev.get("from_phone")
                or "+0"
            )

            if args.dry_run:
                event_count += 1
                continue

            # Append the event to the call's subcollection (creates parent if absent)
            call_store.append_event(
                call_sid=call_sid,
                event=CallEvent(ts=ts, kind=kind, payload=payload),
                caller_phone_for_upsert=caller_phone,
                from_number_for_upsert=payload.get("to") or "+0",
            )
            event_count += 1
            seen_calls.add(call_sid)

            if caller_phone and caller_phone != "+0" and caller_phone not in seen_phones:
                caller_store.upsert_on_call(
                    phone=caller_phone, ts=ts, call_sid=call_sid, outcome="backfilled"
                )
                seen_phones.add(caller_phone)

            if kind == "message_taken":
                msg_store.create(
                    Message(
                        call_sid=call_sid,
                        caller_phone=caller_phone,
                        caller_name=payload.get("caller_name"),
                        reason=payload.get("reason", ""),
                        taken_at=ts,
                    )
                )
                msg_count += 1

    print(
        f"Backfill {'DRY-RUN' if args.dry_run else 'COMPLETE'}: "
        f"{event_count} events, {len(seen_calls)} calls, "
        f"{len(seen_phones)} callers, {msg_count} messages"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
