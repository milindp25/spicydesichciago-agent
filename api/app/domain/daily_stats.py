"""DailyStats domain model — materialized per-day call aggregates.

snake_case Python, camelCase on the wire (Firestore). Translation
happens in to_firestore / from_firestore.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DailyStats(BaseModel):
    date: str  # YYYY-MM-DD, America/Chicago day key
    total_calls: int = 0
    transfers_completed: int = 0
    transfers_failed: int = 0
    messages_taken: int = 0
    computed_at: datetime

    def to_firestore(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "totalCalls": self.total_calls,
            "transfersCompleted": self.transfers_completed,
            "transfersFailed": self.transfers_failed,
            "messagesTaken": self.messages_taken,
            "computedAt": self.computed_at,
        }

    @classmethod
    def from_firestore(cls, data: dict[str, Any]) -> "DailyStats":
        return cls(
            date=data["date"],
            total_calls=data.get("totalCalls", 0),
            transfers_completed=data.get("transfersCompleted", 0),
            transfers_failed=data.get("transfersFailed", 0),
            messages_taken=data.get("messagesTaken", 0),
            computed_at=data["computedAt"],
        )
