import pytest
from pydantic import ValidationError

from app.domain.models import (
    EventRecord,
    HoursStatus,
    HoursToday,
    MessageRequest,
    OwnerAvailable,
    Tenant,
)


def test_hours_today_accepts_valid_status() -> None:
    h = HoursToday(open="11:00", close="21:30", status=HoursStatus.OPEN)
    assert h.status == HoursStatus.OPEN


def test_hours_today_allows_null_open_close_when_closed() -> None:
    h = HoursToday(open=None, close=None, status=HoursStatus.CLOSED)
    assert h.open is None


def test_message_request_requires_callback_number() -> None:
    with pytest.raises(ValidationError):
        MessageRequest(call_sid="CA1", reason="hi")  # type: ignore[call-arg]


def test_tenant_round_trip() -> None:
    t = Tenant(
        slug="spicy-desi",
        name="Spicy Desi",
        twilio_number="+15555550100",
        owner_phone="+15555550199",
        owner_available=OwnerAvailable(tz="America/Chicago", weekly={"mon": ("11:00", "21:30")}),
        square_merchant_id="M1",
        languages=["en"],
        sms_confirmation_to_caller=True,
        location_overrides={},
        faq="",
        location_notes="",
    )
    assert t.slug == "spicy-desi"


def test_event_record_serializes() -> None:
    e = EventRecord(call_sid="CA1", kind="message_taken", payload={"caller": "Asha"})
    assert e.model_dump()["kind"] == "message_taken"
