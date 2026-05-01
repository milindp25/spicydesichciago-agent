from datetime import UTC, datetime

from app.domain.models import OwnerAvailable, Tenant
from app.services.transfer_decision_service import decide_transfer


def _tenant() -> Tenant:
    return Tenant(
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


def test_in_window_returns_transfer() -> None:
    monday2pm = datetime(2026, 1, 5, 20, 0, tzinfo=UTC)
    d = decide_transfer(_tenant(), now=monday2pm)
    assert d.action == "transfer"
    assert d.target == "+15555550199"


def test_outside_window_returns_take_message() -> None:
    monday6am = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    d = decide_transfer(_tenant(), now=monday6am)
    assert d.action == "take_message"


def test_no_window_for_day_returns_take_message() -> None:
    sunday = datetime(2026, 1, 4, 18, 0, tzinfo=UTC)
    d = decide_transfer(_tenant(), now=sunday)
    assert d.action == "take_message"
