"""Caller aggregate (per-phone history)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class Caller(BaseModel):
    phone: str
    first_seen: datetime
    last_seen: datetime
    call_count: int
    last_call_sid: str | None = None
    last_outcome: str | None = None
    notes: str = ""

    def to_firestore(self) -> dict[str, Any]:
        return {
            "firstSeen": self.first_seen,
            "lastSeen": self.last_seen,
            "callCount": self.call_count,
            "lastCallSid": self.last_call_sid,
            "lastOutcome": self.last_outcome,
            "notes": self.notes,
        }

    @classmethod
    def from_firestore(cls, *, phone: str, data: dict[str, Any]) -> Caller:
        return cls(
            phone=phone,
            first_seen=data["firstSeen"],
            last_seen=data["lastSeen"],
            call_count=data["callCount"],
            last_call_sid=data.get("lastCallSid"),
            last_outcome=data.get("lastOutcome"),
            notes=data.get("notes", ""),
        )
