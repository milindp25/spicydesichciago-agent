from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.domain.models import Tenant, TransferDecision
from app.infrastructure.firestore_owner_override_store import FirestoreOwnerOverrideStore


def decide_transfer(
    tenant: Tenant,
    *,
    now: datetime | None = None,
    owner_override_store: FirestoreOwnerOverrideStore | None = None,
) -> TransferDecision:
    current_now = now or datetime.now(UTC)

    # Check day-of override first; if active and not expired, force take_message.
    if owner_override_store is not None:
        override = owner_override_store.get_current()
        if override and override.active and override.until_iso:
            until = datetime.fromisoformat(override.until_iso.replace("Z", "+00:00"))
            if current_now < until:
                return TransferDecision(action="take_message", target=None, reason="override")

    tz = ZoneInfo(tenant.owner_available.tz)
    cur = current_now.astimezone(tz)
    day_key = cur.strftime("%a").lower()[:3]
    window = tenant.owner_available.weekly.get(day_key)
    if window is None:
        return TransferDecision(action="take_message", reason="after_hours")
    cur_hhmm = cur.strftime("%H:%M")
    if window[0] <= cur_hhmm < window[1]:
        return TransferDecision(action="transfer", target=tenant.owner_phone)
    return TransferDecision(action="take_message", reason="after_hours")
