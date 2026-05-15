"""FirestoreDailyStatsStore — read/write /dailyStats/{YYYY-MM-DD}."""
from __future__ import annotations

from google.cloud import firestore

from app.domain.daily_stats import DailyStats

DAILY_STATS_COLLECTION = "dailyStats"


class FirestoreDailyStatsStore:
    def __init__(self, *, client: firestore.Client) -> None:
        self._db = client

    def _ref(self, date_str: str) -> firestore.DocumentReference:
        return self._db.collection(DAILY_STATS_COLLECTION).document(date_str)

    def set(self, stats: DailyStats) -> None:
        """Idempotent — overwrites any existing doc for this date."""
        self._ref(stats.date).set(stats.to_firestore())

    def get(self, date_str: str) -> DailyStats | None:
        snap = self._ref(date_str).get()
        if not snap.exists:
            return None
        return DailyStats.from_firestore(snap.to_dict() or {})
