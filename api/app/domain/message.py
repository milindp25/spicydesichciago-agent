"""Message domain model (caller-left messages)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class MessageStatus(StrEnum):
    NEW = "new"
    HANDLED = "handled"


class Message(BaseModel):
    call_sid: str
    caller_phone: str
    caller_name: str | None = None
    reason: str
    taken_at: datetime
    status: MessageStatus = MessageStatus.NEW
    handled_at: datetime | None = None
    handled_by: str | None = None

    def to_firestore(self) -> dict[str, Any]:
        return {
            "callSid": self.call_sid,
            "callerPhone": self.caller_phone,
            "callerName": self.caller_name,
            "reason": self.reason,
            "takenAt": self.taken_at,
            "status": self.status.value,
            "handledAt": self.handled_at,
            "handledBy": self.handled_by,
        }

    @classmethod
    def from_firestore(cls, *, data: dict[str, Any]) -> Message:
        return cls(
            call_sid=data["callSid"],
            caller_phone=data["callerPhone"],
            caller_name=data.get("callerName"),
            reason=data["reason"],
            taken_at=data["takenAt"],
            status=MessageStatus(data.get("status", MessageStatus.NEW.value)),
            handled_at=data.get("handledAt"),
            handled_by=data.get("handledBy"),
        )
