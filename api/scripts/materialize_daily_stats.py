"""Materialize /dailyStats/{YYYY-MM-DD} from the /calls collection.

Idempotent — re-running for the same date overwrites cleanly.

Usage:
    python -m scripts.materialize_daily_stats --date 2026-05-14
    python -m scripts.materialize_daily_stats --days 7
    python -m scripts.materialize_daily_stats --yesterday

Env (when run against real Firestore):
    FIREBASE_PROJECT_ID, FIREBASE_SERVICE_ACCOUNT_PATH

Schedulable from any cron / Cloud Scheduler.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.infrastructure.firestore_call_store import FirestoreCallStore
from app.infrastructure.firestore_client import FirestoreClient
from app.infrastructure.firestore_daily_stats_store import FirestoreDailyStatsStore
from app.services.daily_stats_materializer import DailyStatsMaterializer

CHICAGO = ZoneInfo("America/Chicago")


def _resolve_dates(args: argparse.Namespace) -> list[str]:
    today_chi = datetime.now(CHICAGO).date()
    if args.date:
        return [args.date]
    if args.yesterday:
        return [(today_chi - timedelta(days=1)).isoformat()]
    if args.days:
        # last N days inclusive of today
        return [
            (today_chi - timedelta(days=i)).isoformat()
            for i in range(args.days - 1, -1, -1)
        ]
    # default: today
    return [today_chi.isoformat()]


def main(
    argv: list[str] | None = None,
    *,
    materializer: DailyStatsMaterializer | None = None,
) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD (America/Chicago)")
    parser.add_argument("--days", type=int, help="Last N days inclusive of today")
    parser.add_argument("--yesterday", action="store_true")
    args = parser.parse_args(argv or [])

    if materializer is None:
        client = FirestoreClient(
            project_id=os.environ.get("FIREBASE_PROJECT_ID", "spicy-desi-chicago"),
            service_account_path=os.environ.get(
                "FIREBASE_SERVICE_ACCOUNT_PATH", ""
            ),
        )
        materializer = DailyStatsMaterializer(
            call_store=FirestoreCallStore(client=client.db),
            stats_store=FirestoreDailyStatsStore(client=client.db),
        )

    rc = 0
    for date_str in _resolve_dates(args):
        try:
            stats = materializer.materialize(date_str)
        except Exception as e:  # noqa: BLE001
            print(
                json.dumps({"date": date_str, "error": str(e)}),
                file=sys.stderr,
            )
            rc = 1
            continue
        print(json.dumps({
            "date": stats.date,
            "totalCalls": stats.total_calls,
            "transfersCompleted": stats.transfers_completed,
            "transfersFailed": stats.transfers_failed,
            "messagesTaken": stats.messages_taken,
        }))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
