"""Owner availability override (singleton, doc id 'current')."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class OwnerOverride(BaseModel):
    active: bool
    until_iso: str | None = None
    reason: str | None = None
    set_by: str
    set_at: datetime

    def to_firestore(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "untilIso": self.until_iso,
            "reason": self.reason,
            "setBy": self.set_by,
            "setAt": self.set_at,
        }

    @classmethod
    def from_firestore(cls, data: dict[str, Any]) -> OwnerOverride:
        return cls(
            active=data["active"],
            until_iso=data.get("untilIso"),
            reason=data.get("reason"),
            set_by=data["setBy"],
            set_at=data["setAt"],
        )
