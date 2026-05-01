from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HoursStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    CLOSING_SOON = "closing_soon"


class LocationListItem(BaseModel):
    location_id: str
    name: str
    address: str


class HoursToday(BaseModel):
    open: str | None
    close: str | None
    status: HoursStatus
    next_open: str | None = None


class AddressInfo(BaseModel):
    formatted: str
    lat: float | None
    lng: float | None


class MenuItem(BaseModel):
    name: str
    description: str
    price: str
    category: str | None
    dietary_tags: list[str] = Field(default_factory=list)


class MessageRequest(BaseModel):
    call_sid: str
    caller_name: str | None = None
    callback_number: str
    reason: str
    language: str | None = None
    location_id: str | None = None


class TransferRequest(BaseModel):
    call_sid: str
    reason: str | None = None
    location_id: str | None = None


class TransferDecision(BaseModel):
    action: str
    target: str | None = None


class PickupToday(BaseModel):
    location_id: str
    name: str
    address: str
    set_at: str
    set_for_date: str
    hours: HoursToday | None = None


class SetPickupRequest(BaseModel):
    tenant: str
    location_id: str


class EventRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    call_sid: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: float | None = None


class OwnerAvailable(BaseModel):
    tz: str
    weekly: dict[str, tuple[str, str]]


class Tenant(BaseModel):
    slug: str
    name: str
    twilio_number: str
    owner_phone: str
    owner_available: OwnerAvailable
    square_merchant_id: str
    languages: list[str]
    sms_confirmation_to_caller: bool
    location_overrides: dict[str, dict[str, Any]]
    faq: str
    location_notes: str
    specials: list[MenuItem] = Field(default_factory=list)
