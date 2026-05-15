"""Pure aggregation of Call list -> DailyStats. No I/O."""
from __future__ import annotations

from datetime import datetime

from app.domain.call import Call, Outcome
from app.domain.daily_stats import DailyStats


def aggregate(date_str: str, calls: list[Call], computed_at: datetime) -> DailyStats:
    transfers_completed = 0
    transfers_failed = 0
    messages_taken = 0
    for c in calls:
        if c.outcome == Outcome.TRANSFERRED:
            transfers_completed += 1
        elif c.outcome == Outcome.FAILED:
            transfers_failed += 1
        elif c.outcome == Outcome.MESSAGE_TAKEN:
            messages_taken += 1
    return DailyStats(
        date=date_str,
        total_calls=len(calls),
        transfers_completed=transfers_completed,
        transfers_failed=transfers_failed,
        messages_taken=messages_taken,
        computed_at=computed_at,
    )
