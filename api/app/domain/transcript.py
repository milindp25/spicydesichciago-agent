"""Transcript domain models — per-call transcript stored at
/calls/{callSid}/transcript/full.

snake_case Python, camelCase on the wire. Translation lives on the
models via to_firestore / from_firestore — matches the existing pattern
in app/domain/call.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class Turn(BaseModel):
    role: Literal["caller", "agent"]
    text: str


class Transcript(BaseModel):
    call_sid: str
    stored_at: datetime
    turns: list[Turn]

    def to_firestore(self) -> dict[str, Any]:
        return {
            "callSid": self.call_sid,
            "storedAt": self.stored_at,
            "turns": [{"role": t.role, "text": t.text} for t in self.turns],
        }

    @classmethod
    def from_firestore(cls, *, call_sid: str, data: dict[str, Any]) -> Transcript:
        raw_turns = data.get("turns", []) or []
        turns = [Turn(role=t["role"], text=t["text"]) for t in raw_turns]
        return cls(
            call_sid=call_sid,
            stored_at=data["storedAt"],
            turns=turns,
        )
