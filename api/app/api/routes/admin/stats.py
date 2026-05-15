"""Dashboard daily-stats endpoint — hybrid materialized + live aggregation.

For each day in the requested window we first try to read the materialized
/dailyStats/{date} doc. If absent (e.g. today, or a day before backfill ran)
we fall back to live aggregation of the /calls collection.

Day boundary is America/Chicago. Cap days at 30 to keep query cost bounded.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from google.cloud import firestore as gfirestore

from app.api.dependencies import AppState, get_state, require_admin_user
from app.domain.call import Outcome

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin_user)])

CHICAGO = ZoneInfo("America/Chicago")


def _materialized_lookup(state: AppState, date_str: str) -> dict[str, Any] | None:
    stats = state.daily_stats_store.get(date_str)
    if stats is None:
        return None
    return {
        "date": stats.date,
        "totalCalls": stats.total_calls,
        "transfersCompleted": stats.transfers_completed,
        "transfersFailed": stats.transfers_failed,
        "messagesTaken": stats.messages_taken,
        "source": "materialized",
    }


def _live_aggregate(
    state: AppState,
    day_start_utc: datetime,
    day_end_utc: datetime,
    date_str: str,
) -> dict[str, Any]:
    db = state.call_store._db
    query = (
        db.collection("calls")
        .where(filter=gfirestore.FieldFilter("startedAt", ">=", day_start_utc))
        .where(filter=gfirestore.FieldFilter("startedAt", "<", day_end_utc))
    )
    total = 0
    transfers = 0
    transfers_failed = 0
    messages = 0
    for snap in query.stream():
        total += 1
        data = snap.to_dict() or {}
        outcome = data.get("outcome")
        if outcome == Outcome.TRANSFERRED.value:
            transfers += 1
        elif outcome == Outcome.FAILED.value:
            transfers_failed += 1
        elif outcome == Outcome.MESSAGE_TAKEN.value:
            messages += 1
    return {
        "date": date_str,
        "totalCalls": total,
        "transfersCompleted": transfers,
        "transfersFailed": transfers_failed,
        "messagesTaken": messages,
        "source": "live",
    }


@router.get("/stats/daily")
async def daily_stats(
    request: Request,
    days: int = Query(7, ge=1),
) -> dict[str, list[dict[str, Any]]]:
    if days > 30:
        raise HTTPException(status_code=400, detail="days must be <= 30")

    state = get_state(request)

    today_chi_start = datetime.now(CHICAGO).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    out: list[dict[str, Any]] = []
    for offset in range(days):
        day_start = today_chi_start - timedelta(days=offset)
        day_end = day_start + timedelta(days=1)
        date_str = day_start.date().isoformat()

        materialized = _materialized_lookup(state, date_str)
        if materialized is not None:
            out.append(materialized)
            continue

        day_start_utc = day_start.astimezone(ZoneInfo("UTC"))
        day_end_utc = day_end.astimezone(ZoneInfo("UTC"))
        out.append(_live_aggregate(state, day_start_utc, day_end_utc, date_str))
    return {"days": out}
