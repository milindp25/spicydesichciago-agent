"""Pickup state record (per-tenant active pickup location)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class PickupRecord(BaseModel):
    location_id: str
    set_at: datetime
    set_for_date: str  # YYYY-MM-DD in America/Chicago

    def to_firestore(self) -> dict[str, Any]:
        return {
            "locationId": self.location_id,
            "setAt": self.set_at,
            "setForDate": self.set_for_date,
        }

    @classmethod
    def from_firestore(cls, data: dict[str, Any]) -> PickupRecord:
        set_at = data["setAt"]
        if isinstance(set_at, str):
            # Back-compat for migrated JSON data: parse ISO string.
            # datetime.fromisoformat handles "+00:00"; tolerate trailing "Z".
            if set_at.endswith("Z"):
                set_at = set_at[:-1] + "+00:00"
            set_at = datetime.fromisoformat(set_at)
        return cls(
            location_id=data["locationId"],
            set_at=set_at,
            set_for_date=data["setForDate"],
        )
