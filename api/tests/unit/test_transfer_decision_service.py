from datetime import UTC, datetime, timedelta, timezone

from app.domain.models import OwnerAvailable, Tenant
from app.domain.owner_override import OwnerOverride
from app.services.transfer_decision_service import decide_transfer


def _tenant() -> Tenant:
    return Tenant(
        slug="spicy-desi",
        name="Spicy Desi",
        twilio_number="+15555550100",
        owner_phone="+15555550199",
        owner_available=OwnerAvailable(tz="America/Chicago", weekly={"mon": ("11:00", "21:30")}),
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


class _StubOverrideStore:
    def __init__(self, override: OwnerOverride | None) -> None:
        self._override = override

    def get_current(self) -> OwnerOverride | None:
        return self._override


def test_active_override_forces_take_message() -> None:
    # Monday 2pm — would normally be "transfer"
    monday2pm = datetime(2026, 1, 5, 20, 0, tzinfo=UTC)
    until = (monday2pm + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    override_store = _StubOverrideStore(
        OwnerOverride(
            active=True,
            until_iso=until,
            reason="wedding",
            set_by="uid-owner",
            set_at=datetime.now(timezone.utc),
        )
    )
    d = decide_transfer(_tenant(), now=monday2pm, owner_override_store=override_store)
    assert d.action == "take_message"
    assert d.target is None


def test_expired_override_falls_through() -> None:
    # Monday 2pm — should still transfer because override expired
    monday2pm = datetime(2026, 1, 5, 20, 0, tzinfo=UTC)
    until = (monday2pm - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    override_store = _StubOverrideStore(
        OwnerOverride(
            active=True,
            until_iso=until,
            reason="wedding",
            set_by="uid-owner",
            set_at=monday2pm - timedelta(hours=3),
        )
    )
    d = decide_transfer(_tenant(), now=monday2pm, owner_override_store=override_store)
    assert d.action == "transfer"
    assert d.target == "+15555550199"
