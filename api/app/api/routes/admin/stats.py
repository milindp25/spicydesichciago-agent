"""Dashboard daily-stats endpoint — computed live from /calls.

Day boundary is America/Chicago. Cap days at 30 to keep query cost bounded.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from google.cloud import firestore as gfirestore

from app.api.dependencies import get_state, require_admin_user
from app.domain.call import Outcome

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin_user)])

CHICAGO = ZoneInfo("America/Chicago")


@router.get("/stats/daily")
async def daily_stats(
    request: Request,
    days: int = Query(7, ge=1),
) -> dict[str, list[dict[str, Any]]]:
    if days > 30:
        raise HTTPException(status_code=400, detail="days must be <= 30")

    state = get_state(request)
    db = state.call_store._db  # access for raw query

    today_chi_start = datetime.now(CHICAGO).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    out: list[dict[str, Any]] = []
    for offset in range(days):
        day_start = today_chi_start - timedelta(days=offset)
        day_end = day_start + timedelta(days=1)
        day_start_utc = day_start.astimezone(ZoneInfo("UTC"))
        day_end_utc = day_end.astimezone(ZoneInfo("UTC"))

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

        out.append(
            {
                "date": day_start.date().isoformat(),
                "totalCalls": total,
                "transfersCompleted": transfers,
                "transfersFailed": transfers_failed,
                "messagesTaken": messages,
            }
        )
    return {"days": out}
