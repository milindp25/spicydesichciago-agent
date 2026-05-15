"""DailyStatsMaterializer — compute and persist /dailyStats/{date}.

Day boundary is America/Chicago, consistent with /api/admin/stats/daily.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.daily_stats import DailyStats
from app.infrastructure.firestore_call_store import FirestoreCallStore
from app.infrastructure.firestore_daily_stats_store import FirestoreDailyStatsStore
from app.services.daily_stats_aggregator import aggregate

CHICAGO = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")


def chicago_day_window_utc(date_str: str) -> tuple[datetime, datetime]:
    """Return [start_utc, end_utc) for the given YYYY-MM-DD Chicago date."""
    y, m, d = (int(x) for x in date_str.split("-"))
    start_chi = datetime(y, m, d, 0, 0, 0, tzinfo=CHICAGO)
    end_chi = start_chi + timedelta(days=1)
    return start_chi.astimezone(UTC), end_chi.astimezone(UTC)


class DailyStatsMaterializer:
    def __init__(
        self,
        *,
        call_store: FirestoreCallStore,
        stats_store: FirestoreDailyStatsStore,
    ) -> None:
        self._call_store = call_store
        self._stats_store = stats_store

    def materialize(
        self, date_str: str, *, now: datetime | None = None
    ) -> DailyStats:
        start_utc, end_utc = chicago_day_window_utc(date_str)
        calls = self._call_store.list_in_window(start_utc=start_utc, end_utc=end_utc)
        computed_at = now if now is not None else datetime.now(UTC)
        stats = aggregate(date_str, calls, computed_at)
        self._stats_store.set(stats)
        return stats
