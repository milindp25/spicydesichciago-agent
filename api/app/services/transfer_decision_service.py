from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.domain.models import Tenant, TransferDecision


def decide_transfer(tenant: Tenant, *, now: datetime | None = None) -> TransferDecision:
    tz = ZoneInfo(tenant.owner_available.tz)
    cur = (now or datetime.now(UTC)).astimezone(tz)
    day_key = cur.strftime("%a").lower()[:3]
    window = tenant.owner_available.weekly.get(day_key)
    if window is None:
        return TransferDecision(action="take_message")
    cur_hhmm = cur.strftime("%H:%M")
    if window[0] <= cur_hhmm < window[1]:
        return TransferDecision(action="transfer", target=tenant.owner_phone)
    return TransferDecision(action="take_message")
