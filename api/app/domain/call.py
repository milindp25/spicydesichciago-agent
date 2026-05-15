"""Call and CallEvent domain models.

snake_case Python, camelCase on the wire (Firestore). Translation
happens in to_firestore / from_firestore.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Outcome(StrEnum):
    IN_PROGRESS = "inProgress"
    RESOLVED = "resolved"
    TRANSFERRED = "transferred"
    MESSAGE_TAKEN = "messageTaken"
    FAILED = "failed"


class EventKind(StrEnum):
    """Canonical taxonomy of CallEvent.kind values.

    CallEvent.kind is intentionally typed as `str` (not narrowed to this enum)
    so unknown / legacy kinds from older Firestore data still parse. Emitters
    should pass `EventKind.X.value` to keep the wire format consistent.
    """

    CALL_STARTED = "callStarted"
    CALL_ENDED = "callEnded"
    CALL_SUMMARY = "callSummary"
    TRANSFER_DECIDED = "transferDecided"
    TRANSFER_INITIATED = "transferInitiated"
    TRANSFER_COMPLETED = "transferCompleted"
    TRANSFER_FAILED = "transferFailed"
    MESSAGE_TAKEN = "messageTaken"
    SMS_LINK_SENT = "smsLinkSent"
    TOOL_CALLED = "toolCalled"
    TOOL_ERROR = "toolError"


class Call(BaseModel):
    call_sid: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    caller_phone: str
    from_number: str
    outcome: Outcome = Outcome.IN_PROGRESS
    summary: str | None = None
    tools_used: list[str] = Field(default_factory=list)

    def to_firestore(self) -> dict[str, Any]:
        return {
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "durationMs": self.duration_ms,
            "callerPhone": self.caller_phone,
            "fromNumber": self.from_number,
            "outcome": self.outcome.value,
            "summary": self.summary,
            "toolsUsed": list(self.tools_used),
        }

    @classmethod
    def from_firestore(cls, *, call_sid: str, data: dict[str, Any]) -> Call:
        return cls(
            call_sid=call_sid,
            started_at=data["startedAt"],
            ended_at=data.get("endedAt"),
            duration_ms=data.get("durationMs"),
            caller_phone=data["callerPhone"],
            from_number=data["fromNumber"],
            outcome=Outcome(data.get("outcome", Outcome.IN_PROGRESS.value)),
            summary=data.get("summary"),
            tools_used=data.get("toolsUsed", []),
        )


class CallEvent(BaseModel):
    ts: datetime
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_firestore(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "kind": self.kind,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_firestore(cls, data: dict[str, Any]) -> CallEvent:
        return cls(ts=data["ts"], kind=data["kind"], payload=data.get("payload", {}))
