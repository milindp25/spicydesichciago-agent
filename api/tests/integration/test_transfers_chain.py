"""Integration tests: /api/transfers includes the escalation chain in the
redirect URL when the tenant has one configured."""
from __future__ import annotations

import base64
import json
from collections.abc import Callable

from fastapi.testclient import TestClient

from app.api.dependencies import AppState
from app.domain.models import EscalationContact


def _decode_chain(encoded: str) -> list[dict]:
    padded = encoded + "=" * (-len(encoded) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))


def test_transfer_omits_chain_when_escalation_empty(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, state = client_factory(agent_public_url="https://agent.example.com")
    # Default tenant has escalation=[] (see conftest._build_tenant).
    r = c.post(
        "/api/transfers?now=2026-01-05T20:00:00Z",
        headers=auth_headers,
        json={"call_sid": "CA1", "reason": "owner please"},
    )
    assert r.status_code == 200
    assert len(state.twilio.redirects) == 1
    twiml_url = state.twilio.redirects[0]["twiml_url"]
    # No chain query param when escalation list is empty.
    assert "chain=" not in twiml_url
    assert twiml_url == (
        "https://agent.example.com/twilio/dial-owner?to=+15555550199"
    )


def test_transfer_includes_chain_when_escalation_configured(
    client_factory: Callable[..., tuple[TestClient, AppState]],
    auth_headers: dict[str, str],
) -> None:
    c, state = client_factory(agent_public_url="https://agent.example.com")
    # Inject one escalation contact into the tenant.
    tenant = state.tenants.tenants["spicy-desi"]
    tenant.escalation.append(
        EscalationContact(phone="+13125550100", timeout_seconds=30, label="manager")
    )
    r = c.post(
        "/api/transfers?now=2026-01-05T20:00:00Z",
        headers=auth_headers,
        json={"call_sid": "CA1", "reason": "owner please"},
    )
    assert r.status_code == 200
    assert len(state.twilio.redirects) == 1
    twiml_url = state.twilio.redirects[0]["twiml_url"]
    assert "chain=" in twiml_url
    chain_param = twiml_url.split("chain=", 1)[1]
    decoded = _decode_chain(chain_param)
    assert decoded == [
        {"phone": "+13125550100", "timeout_seconds": 30, "label": "manager"}
    ]
