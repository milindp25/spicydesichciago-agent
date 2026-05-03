# Plan 2 — Pipecat voice agent + Twilio integration

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stand up the actual phone agent. Customers call a Twilio number, Pipecat handles the voice loop (Silero VAD → Deepgram STT (multilingual) → Groq Llama 3.3 70B with tool calls → Cartesia Sonic-2 multilingual TTS), tools call into the Plan 1 API for menu/pickup/etc., and the agent transfers to owner or takes a message when needed. Plus: wire the real Twilio SMS in `/api/messages` and the real Twilio REST live-call redirect in `/api/transfers` (currently stubs).

**v1 language scope:** English + Hindi + Telugu. Detected automatically by Deepgram `language=multi`; agent responds in caller's language using Cartesia's multilingual voice. We test Telugu samples before launch — if quality is poor, we fall back to Hindi+English only.

**End state:** A real phone call to a real Twilio number gets answered by the AI agent. Caller can ask "where are you today?", "what's on the menu?", "what are your specials?", "are you open?". They can ask for the owner — gets transferred when in-hours, take-message + SMS otherwise.

**Architecture:**

```
Caller → Twilio number
         │
         ▼ Webhook: POST /twilio/inbound (TwiML response opens Media Stream)
         ▼ WSS:    /twilio/stream
         │
         ▼
  Pipecat pipeline (agent/ — separate Python service):
    Silero VAD
      → Deepgram Nova-3 STT (language=multi)
      → Groq Llama 3.3 70B (with tool calls)
      → Cartesia Sonic-2 multilingual TTS
      → back to Twilio

  Tool calls from LLM → HTTP → Plan 1 API (api/, with X-Tools-Auth):
    /api/pickup/today                  → "where are you today?"
    /api/menu/search?q=…               → "do you have X?"
    /api/specials                      → "what are your specials?"
    /api/messages                      → take a message
    /api/transfers                     → transfer to owner / take_message decision
    /api/calls/{sid}/event             → log transcript chunks

  Plan 1 API additions:
    twilio_service.send_sms(...)       → wired into /api/messages
    twilio_service.redirect_call(...)  → wired into /api/transfers
```

**Tech Stack additions:**
- Python 3.11+ for `agent/`
- Pipecat (voice-agent framework)
- Twilio (telephony + SMS REST + Media Streams)
- Groq SDK (Llama 3.3 70B)
- Deepgram SDK (STT)
- Cartesia SDK (TTS — multilingual, ~$5/mo Hobby tier covers v1 dev + initial production)
- ngrok (local dev — exposes localhost to Twilio for inbound webhooks)

---

## Phase 0 — accounts (do before Task 1)

External setup. Plan 2 depends on these.

- [ ] **Twilio account** — create at twilio.com (free trial credit). Provision a phone number with **Voice + SMS** capabilities. Note: Account SID, Auth Token, phone number.
- [ ] **Groq API key** — console.groq.com → create key. Free tier auto-applied.
- [ ] **Deepgram API key** — console.deepgram.com → create key. Claim $200 free credit.
- [ ] **Cartesia API key + multilingual voice** — play.cartesia.ai. Upgrade to Hobby tier ($5/mo) since the free tier credits are exhausted. Browse Sonic-2 multilingual voices, listen to BOTH a Hindi sample AND a Telugu sample for each candidate, and pick one that sounds clean in all three languages. Note the `voice_id`.
- [ ] **ngrok** — `brew install ngrok` and `ngrok config add-authtoken …` (free tier is fine for dev).
- [ ] **Twilio number webhook config — DO LATER** (Task 12) — once the local server is reachable via ngrok, configure the Twilio number's "A call comes in" webhook to `https://<ngrok-domain>/twilio/inbound`.

---

## File Structure

```
agent/                                # NEW — separate service
  pyproject.toml
  .env.example
  .python-version
  README.md
  app/
    __init__.py
    main.py                           # uvicorn target
    server.py                         # FastAPI: /twilio/inbound + /twilio/stream WS
    bot.py                            # Pipecat pipeline factory
    config.py                         # AgentSettings (pydantic-settings)
    prompts/
      system.md                       # Agent personality + escalation rules
    tools/
      __init__.py
      api_client.py                   # httpx client to Plan 1 API (X-Tools-Auth)
      definitions.py                  # Tool schemas for Groq function calling
      handlers.py                     # handle each tool call (route to api_client)
  tests/
    __init__.py
    conftest.py
    helpers/
      api_mock.py                     # Mock Plan 1 API for unit tests
    unit/
      test_api_client.py
      test_handlers.py
      test_tool_definitions.py

api/                                  # MODIFIED
  app/
    infrastructure/
      twilio_client.py                # NEW — wraps Twilio REST API
    api/routes/
      messages.py                     # MODIFIED — sends real SMS via twilio_client
      transfers.py                    # MODIFIED — redirects live call via twilio_client
    api/app_factory.py                # MODIFIED — adds CORSMiddleware
  tests/
    unit/test_twilio_client.py        # NEW
    integration/test_messages_route.py # MODIFIED
    integration/test_transfers_route.py # MODIFIED
```

---

## Task 1: Wire Twilio into Plan 1 API — SMS infrastructure

**Goal:** make `/api/messages` actually SMS the owner instead of just logging.

**Files:**
- Modify: `api/pyproject.toml` — add `twilio` dependency
- Modify: `api/.env.example` + `api/app/infrastructure/config.py` — Twilio creds
- Create: `api/app/infrastructure/twilio_client.py`
- Create: `api/tests/unit/test_twilio_client.py`

- [ ] **Step 1: Add Twilio settings**

In `api/app/infrastructure/config.py`, add to `AppSettings`:

```python
    twilio_account_sid: str = Field("", alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field("", alias="TWILIO_AUTH_TOKEN")
    twilio_from_number: str = Field("", alias="TWILIO_FROM_NUMBER")
    twilio_signing_secret: str = Field("", alias="TWILIO_SIGNING_SECRET")
```

(All blank-defaulted so dev/test environments without Twilio still boot.)

In `api/.env.example`, add:

```
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
TWILIO_SIGNING_SECRET=
```

In `api/pyproject.toml`, add `twilio>=9.3.0` to dependencies.

- [ ] **Step 2: Implement `api/app/infrastructure/twilio_client.py`**

```python
from __future__ import annotations

import logging
from typing import Protocol

from twilio.rest import Client as TwilioRestClient

log = logging.getLogger(__name__)


class TwilioOps(Protocol):
    async def send_sms(self, *, to: str, body: str) -> bool: ...
    async def redirect_call(self, *, call_sid: str, twiml_url: str) -> bool: ...


class RealTwilioClient:
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self._client = TwilioRestClient(account_sid, auth_token) if account_sid else None
        self._from = from_number

    async def send_sms(self, *, to: str, body: str) -> bool:
        if self._client is None or not self._from:
            log.warning("twilio not configured; skipping send_sms", extra={"to": to})
            return False
        try:
            self._client.messages.create(to=to, from_=self._from, body=body)
            return True
        except Exception:
            log.exception("twilio send_sms failed", extra={"to": to})
            return False

    async def redirect_call(self, *, call_sid: str, twiml_url: str) -> bool:
        if self._client is None:
            log.warning("twilio not configured; skipping redirect_call",
                        extra={"call_sid": call_sid})
            return False
        try:
            self._client.calls(call_sid).update(url=twiml_url, method="POST")
            return True
        except Exception:
            log.exception("twilio redirect_call failed", extra={"call_sid": call_sid})
            return False


class NoopTwilioClient:
    """Used in dev/test when Twilio creds aren't set."""
    async def send_sms(self, *, to: str, body: str) -> bool:
        return False

    async def redirect_call(self, *, call_sid: str, twiml_url: str) -> bool:
        return False
```

- [ ] **Step 3: Add to `AppState` in `api/app/api/dependencies.py`**

```python
    twilio: TwilioOps
```

- [ ] **Step 4: Wire in `api/app/main.py`**

```python
twilio = (
    RealTwilioClient(
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
        from_number=settings.twilio_from_number,
    )
    if settings.twilio_account_sid
    else NoopTwilioClient()
)
```

Pass `twilio=twilio` into `AppState(...)`.

- [ ] **Step 5: Unit test in `api/tests/unit/test_twilio_client.py`**

```python
import pytest
from app.infrastructure.twilio_client import NoopTwilioClient


async def test_noop_send_sms_returns_false() -> None:
    c = NoopTwilioClient()
    assert await c.send_sms(to="+15555550100", body="hi") is False


async def test_noop_redirect_call_returns_false() -> None:
    c = NoopTwilioClient()
    assert await c.redirect_call(call_sid="CA1", twiml_url="https://x") is False
```

(We don't unit-test `RealTwilioClient` here — too much mocking of Twilio SDK. We rely on the integration tests with a fake TwilioOps protocol stub.)

- [ ] **Step 6: Update `api/tests/conftest.py`**

Add a `FakeTwilioClient` recording calls, inject into `AppState`:

```python
class FakeTwilioClient:
    def __init__(self) -> None:
        self.sms_calls: list[dict] = []
        self.redirects: list[dict] = []
    async def send_sms(self, *, to: str, body: str) -> bool:
        self.sms_calls.append({"to": to, "body": body})
        return True
    async def redirect_call(self, *, call_sid: str, twiml_url: str) -> bool:
        self.redirects.append({"call_sid": call_sid, "twiml_url": twiml_url})
        return True
```

Pass into `AppState(twilio=FakeTwilioClient(), ...)`.

- [ ] **Step 7: Run + commit**

```bash
cd api && pytest && ruff check . && ruff format --check .
git add api/pyproject.toml api/.env.example api/app/infrastructure/config.py \
        api/app/infrastructure/twilio_client.py api/app/api/dependencies.py \
        api/app/main.py api/tests/unit/test_twilio_client.py api/tests/conftest.py
git commit -m "feat(api): twilio_client (SMS + redirect_call) — noop fallback when unconfigured"
```

---

## Task 2: Wire SMS into `/api/messages`

**Files:**
- Modify: `api/app/api/routes/messages.py`
- Modify: `api/tests/integration/test_messages_route.py`

- [ ] **Step 1: Update the route**

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_state, require_tools_auth
from app.domain.models import EventRecord, MessageRequest

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.post("/messages", status_code=202)
async def take_message(request: Request, body: MessageRequest) -> dict[str, Any]:
    state = get_state(request)
    tenant = state.tenants.tenants.get("spicy-desi")
    if tenant is None:
        raise HTTPException(404, "tenant not found")

    sms_body = (
        f"Spicy Desi AI message — {body.caller_name or 'unknown'} "
        f"({body.callback_number}): {body.reason}"
    )
    sms_sent = await state.twilio.send_sms(to=tenant.owner_phone, body=sms_body)

    if tenant.sms_confirmation_to_caller and body.callback_number:
        confirmation = (
            f"Thanks for calling Spicy Desi. We got your message about "
            f"\"{body.reason}\" and will call you back."
        )
        await state.twilio.send_sms(to=body.callback_number, body=confirmation)

    await state.event_log.append(
        EventRecord(
            call_sid=body.call_sid,
            kind="message_taken",
            payload={**body.model_dump(), "sms_sent": sms_sent},
        )
    )
    return {"ok": True, "sms_sent": sms_sent}
```

- [ ] **Step 2: Update test to verify SMS dispatched**

```python
def test_messages_records_event_and_sends_sms_to_owner(
    client_factory, auth_headers
) -> None:
    c, state = client_factory()
    r = c.post(
        "/api/messages",
        headers=auth_headers,
        json={"call_sid": "CA1", "callback_number": "+13125551111", "reason": "catering"},
    )
    assert r.status_code == 202
    assert r.json()["sms_sent"] is True
    assert len(state.twilio.sms_calls) == 2  # owner + caller confirmation
    owner_msg = state.twilio.sms_calls[0]
    assert owner_msg["to"] == "+15555550199"  # tenant.owner_phone
    assert "catering" in owner_msg["body"]
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/integration/test_messages_route.py -v
git add api/app/api/routes/messages.py api/tests/integration/test_messages_route.py
git commit -m "feat(api): /api/messages now sends real SMS via Twilio"
```

---

## Task 3: Wire live-call redirect into `/api/transfers`

**Files:**
- Modify: `api/app/api/routes/transfers.py`
- Modify: `api/app/infrastructure/config.py` — add `agent_public_url` (used to build TwiML URL)
- Modify: `api/tests/integration/test_transfers_route.py`

- [ ] **Step 1: Add config**

In `AppSettings`:

```python
    agent_public_url: str = Field("", alias="AGENT_PUBLIC_URL")
```

This is the public URL where the agent's TwiML endpoint is reachable (Plan 3: Caddy domain; for local dev: ngrok tunnel).

- [ ] **Step 2: Update transfers route**

```python
@router.post("/transfers")
async def request_transfer(
    request: Request, body: TransferRequest, now: str | None = Query(None)
) -> dict[str, Any]:
    state = get_state(request)
    tenant = state.tenants.tenants.get("spicy-desi")
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00")) if now else None
    decision = decide_transfer(tenant, now=now_dt)

    redirect_ok = False
    if decision.action == "transfer" and state.agent_public_url:
        twiml_url = f"{state.agent_public_url}/twilio/dial-owner?to={tenant.owner_phone}"
        redirect_ok = await state.twilio.redirect_call(
            call_sid=body.call_sid, twiml_url=twiml_url,
        )

    await state.event_log.append(
        EventRecord(
            call_sid=body.call_sid,
            kind="transfer_decided",
            payload={"decision": decision.model_dump(), "reason": body.reason,
                     "redirect_ok": redirect_ok},
        )
    )
    return {**decision.model_dump(), "redirect_ok": redirect_ok}
```

Pass `agent_public_url` through `AppState`.

- [ ] **Step 3: Update tests** — assert `state.twilio.redirects` has the right call_sid + twiml_url when in-hours.

- [ ] **Step 4: Run + commit**

---

## Task 3.5: SMS today's pickup address to caller (`POST /api/pickup/sms`)

**Goal:** new agent-callable endpoint that texts the caller today's pickup spot — name + address + tap-to-open Google Maps link. Agent uses this when caller wants the location written down.

**Files:**
- Create: `api/app/api/routes/pickup_sms.py`
- Modify: `api/app/api/app_factory.py` (mount router)
- Modify: `api/app/services/pickup_service.py` — add `format_sms_body(pickup) -> str`
- Modify: `api/app/domain/models.py` — add `SmsPickupRequest` model
- Create: `api/tests/integration/test_pickup_sms_route.py`

- [ ] **Step 1: Domain model**

In `api/app/domain/models.py`:

```python
class SmsPickupRequest(BaseModel):
    tenant: str
    to_number: str
    call_sid: str | None = None  # for event-log correlation
```

- [ ] **Step 2: Add SMS body formatter to `PickupService`**

In `api/app/services/pickup_service.py`:

```python
from urllib.parse import quote_plus


def build_pickup_sms_body(pickup: PickupToday) -> str:
    address = pickup.address or "address coming soon"
    maps_link = f"https://maps.google.com/?q={quote_plus(address)}"
    if pickup.hours and pickup.hours.is_open_now and pickup.hours.close_human:
        line2 = f"Open now until {pickup.hours.close_human} {pickup.hours.tz_label}."
    elif pickup.hours and pickup.hours.next_open_weekday and pickup.hours.next_open_time_human:
        line2 = (
            f"Closed right now. Next open: {pickup.hours.next_open_weekday} at "
            f"{pickup.hours.next_open_time_human} {pickup.hours.tz_label}."
        )
    else:
        line2 = ""
    parts = [f"Spicy Desi today: {pickup.name}", address, line2, maps_link]
    return "\n".join(p for p in parts if p)
```

- [ ] **Step 3: Implement the route**

`api/app/api/routes/pickup_sms.py`:

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_state, require_tools_auth
from app.domain.models import EventRecord, SmsPickupRequest
from app.services.pickup_service import build_pickup_sms_body

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.post("/pickup/sms")
async def sms_pickup(request: Request, body: SmsPickupRequest) -> dict[str, Any]:
    state = get_state(request)
    if body.tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    pickup = await state.pickup_service.get_today(body.tenant)
    if pickup is None:
        raise HTTPException(409, "no pickup set for today")
    sms_body = build_pickup_sms_body(pickup)
    sent = await state.twilio.send_sms(to=body.to_number, body=sms_body)
    await state.event_log.append(
        EventRecord(
            call_sid=body.call_sid or "n/a",
            kind="pickup_sms_sent",
            payload={
                "to": body.to_number,
                "location_id": pickup.location_id,
                "sent": sent,
            },
        )
    )
    return {"ok": True, "sent": sent}
```

Mount in `app_factory.py`:

```python
from app.api.routes import ..., pickup_sms
app.include_router(pickup_sms.router)
```

- [ ] **Step 4: Integration tests**

`api/tests/integration/test_pickup_sms_route.py`:

```python
def test_sms_pickup_sends_when_set(client_factory, auth_headers) -> None:
    SAMPLE = [{
        "id": "L1", "name": "29th Street Near PS",
        "address": {"address_line_1": "29th & Halsted"},
        "business_hours": {"periods": []},
        "timezone": "America/Chicago",
    }]
    c, state = client_factory(locations=SAMPLE)
    # Set today's pickup first
    c.post("/api/admin/pickup", headers=auth_headers,
           json={"tenant": "spicy-desi", "location_id": "L1"})
    # Now request SMS
    r = c.post("/api/pickup/sms", headers=auth_headers,
               json={"tenant": "spicy-desi", "to_number": "+13125550123"})
    assert r.status_code == 200
    assert r.json()["sent"] is True
    assert len(state.twilio.sms_calls) == 1
    msg = state.twilio.sms_calls[0]
    assert msg["to"] == "+13125550123"
    assert "29th Street Near PS" in msg["body"]
    assert "29th & Halsted" in msg["body"]
    assert "maps.google.com" in msg["body"]


def test_sms_pickup_409_when_unset(client_factory, auth_headers) -> None:
    c, _ = client_factory(locations=[])
    r = c.post("/api/pickup/sms", headers=auth_headers,
               json={"tenant": "spicy-desi", "to_number": "+13125550123"})
    assert r.status_code == 409


def test_sms_pickup_404_unknown_tenant(client_factory, auth_headers) -> None:
    c, _ = client_factory(locations=[])
    r = c.post("/api/pickup/sms", headers=auth_headers,
               json={"tenant": "nope", "to_number": "+13125550123"})
    assert r.status_code == 404


def test_sms_pickup_requires_auth(client_factory) -> None:
    c, _ = client_factory(locations=[])
    r = c.post("/api/pickup/sms",
               json={"tenant": "spicy-desi", "to_number": "+13125550123"})
    assert r.status_code == 401
```

- [ ] **Step 5: Run + commit**

```bash
cd api && pytest tests/integration/test_pickup_sms_route.py -v
git add api/app/domain/models.py api/app/services/pickup_service.py \
        api/app/api/routes/pickup_sms.py api/app/api/app_factory.py \
        api/tests/integration/test_pickup_sms_route.py
git commit -m "feat(api): POST /api/pickup/sms — text caller today's pickup + maps link"
```

---

## Task 4: CORS middleware (for the admin panel)

**Files:**
- Modify: `api/app/infrastructure/config.py` — add `cors_origins` (comma-separated env var)
- Modify: `api/app/api/app_factory.py` — install `CORSMiddleware`

- [ ] **Step 1: Config**

```python
    cors_origins: str = Field("", alias="CORS_ORIGINS")  # comma-separated

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
```

- [ ] **Step 2: Install middleware**

In `app_factory.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

def build_app(deps: AppState) -> FastAPI:
    app = FastAPI(title="Spicy Desi API")
    app.state.deps = deps

    if deps.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=deps.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["X-Tools-Auth", "Content-Type"],
            allow_credentials=False,
        )
    # …rest unchanged
```

Pass `cors_origins=settings.cors_origin_list` through `AppState`.

- [ ] **Step 3: Test that preflight works**

```python
def test_cors_preflight_allowed_origin(client_factory) -> None:
    # Build with a custom origin
    c, _ = client_factory(cors_origins=["https://admin.example.com"])
    r = c.options(
        "/api/specials",
        headers={
            "Origin": "https://admin.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "https://admin.example.com"
```

- [ ] **Step 4: Commit**

---

## Task 5: Scaffold the `agent/` Python service

**Files:**
- Create: `agent/pyproject.toml`
- Create: `agent/.python-version`
- Create: `agent/.env.example`
- Create: `agent/README.md`
- Create: `agent/app/__init__.py`

- [ ] **Step 1: `agent/pyproject.toml`**

```toml
[project]
name = "spicy-desi-agent"
version = "0.1.0"
description = "Spicy Desi voice agent (Pipecat + Twilio + Groq + Deepgram + Cartesia)"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.32.0",
  "pydantic>=2.9.0",
  "pydantic-settings>=2.6.0",
  "structlog>=24.4.0",
  "httpx>=0.27.0",
  "python-dotenv>=1.0.0",

  # Pipecat + voice providers
  "pipecat-ai[silero,deepgram,cartesia,groq,twilio]>=0.0.50",

  # Twilio for outbound SMS / call control inside the agent (rare; mostly the API does it)
  "twilio>=9.3.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3.0",
  "pytest-asyncio>=0.24.0",
  "ruff>=0.7.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 2: `agent/.env.example`**

```
PORT=8090
LOG_LEVEL=info
APP_ENV=development

# Plan 1 API (where this agent calls for tools)
TOOLS_API_BASE=http://localhost:8080
TOOLS_SHARED_SECRET=replace-with-the-same-32-char-secret-as-the-API

# Tenant bound to this agent process (later: lookup by Twilio number)
DEFAULT_TENANT=spicy-desi

# Voice providers
GROQ_API_KEY=
DEEPGRAM_API_KEY=
CARTESIA_API_KEY=
CARTESIA_VOICE_ID=

# Twilio (for inbound webhook signature verification)
TWILIO_AUTH_TOKEN=
```

- [ ] **Step 3: Install + commit**

```bash
cd agent
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
git add agent/pyproject.toml agent/.python-version agent/.env.example agent/README.md agent/app/__init__.py
git commit -m "chore(agent): scaffold Pipecat voice-agent project"
```

---

## Task 6: Agent config + API client

**Files:**
- Create: `agent/app/config.py`
- Create: `agent/app/tools/__init__.py`
- Create: `agent/app/tools/api_client.py`
- Create: `agent/tests/unit/test_api_client.py`
- Create: `agent/tests/conftest.py`
- Create: `agent/tests/helpers/api_mock.py`

- [ ] **Step 1: `agent/app/config.py`** (Pydantic settings)

```python
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=False, extra="ignore")

    port: int = Field(8090, alias="PORT")
    log_level: str = Field("info", alias="LOG_LEVEL")

    tools_api_base: str = Field(..., alias="TOOLS_API_BASE")
    tools_shared_secret: str = Field(..., alias="TOOLS_SHARED_SECRET", min_length=32)
    default_tenant: str = Field("spicy-desi", alias="DEFAULT_TENANT")

    groq_api_key: str = Field(..., alias="GROQ_API_KEY", min_length=1)
    deepgram_api_key: str = Field(..., alias="DEEPGRAM_API_KEY", min_length=1)
    cartesia_api_key: str = Field(..., alias="CARTESIA_API_KEY", min_length=1)
    cartesia_voice_id: str = Field(..., alias="CARTESIA_VOICE_ID", min_length=1)

    twilio_auth_token: str = Field("", alias="TWILIO_AUTH_TOKEN")
```

- [ ] **Step 2: `agent/app/tools/api_client.py`**

```python
from __future__ import annotations

from typing import Any

import httpx


class ApiClient:
    def __init__(self, *, base_url: str, secret: str, tenant: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Tools-Auth": secret},
            timeout=10.0,
        )
        self._tenant = tenant

    async def get_pickup_today(self) -> dict[str, Any]:
        r = await self._client.get("/api/pickup/today", params={"tenant": self._tenant})
        r.raise_for_status()
        return r.json()

    async def search_menu(self, query: str) -> dict[str, Any]:
        r = await self._client.get(
            "/api/menu/search", params={"tenant": self._tenant, "q": query}
        )
        r.raise_for_status()
        return r.json()

    async def get_specials(self) -> dict[str, Any]:
        r = await self._client.get("/api/specials", params={"tenant": self._tenant})
        r.raise_for_status()
        return r.json()

    async def take_message(
        self, *, call_sid: str, callback_number: str, reason: str,
        caller_name: str | None = None, language: str | None = None,
    ) -> dict[str, Any]:
        r = await self._client.post("/api/messages", json={
            "call_sid": call_sid, "callback_number": callback_number,
            "reason": reason, "caller_name": caller_name, "language": language,
        })
        r.raise_for_status()
        return r.json()

    async def request_transfer(
        self, *, call_sid: str, reason: str | None = None,
    ) -> dict[str, Any]:
        r = await self._client.post("/api/transfers", json={
            "call_sid": call_sid, "reason": reason,
        })
        r.raise_for_status()
        return r.json()

    async def append_event(
        self, *, call_sid: str, kind: str, payload: dict[str, Any],
    ) -> None:
        await self._client.post(
            f"/api/calls/{call_sid}/event",
            json={"kind": kind, "payload": payload},
        )

    async def sms_pickup_address(
        self, *, to_number: str, call_sid: str | None = None,
    ) -> dict[str, Any]:
        r = await self._client.post("/api/pickup/sms", json={
            "tenant": self._tenant, "to_number": to_number, "call_sid": call_sid,
        })
        r.raise_for_status()
        return r.json()

    async def aclose(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 3: Tests via `respx` or recorded responses**

```python
import httpx
import pytest

from app.tools.api_client import ApiClient


async def test_get_pickup_today(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(
        200, json={"pickup": {"name": "29th Street", "summary": "We're open …"}},
    ))
    c = ApiClient(base_url="http://x", secret="s"*32, tenant="spicy-desi")
    c._client = httpx.AsyncClient(transport=transport, headers={"X-Tools-Auth": "s"*32})
    r = await c.get_pickup_today()
    assert r["pickup"]["name"] == "29th Street"
```

(Add `respx` or use `httpx.MockTransport` directly — no new dependency needed for the latter.)

- [ ] **Step 4: Commit**

---

## Task 7: System prompt

**Files:**
- Create: `agent/app/prompts/system.md`

- [ ] **Step 1: Write the prompt**

```markdown
You are a friendly, helpful AI phone assistant for Spicy Desi, a Chicago food truck serving Indian street food (chaat, momos, indo-Chinese, south Indian, and more).

# Tone
Warm, brief, conversational. You are speaking — not writing. Use contractions. One sentence per turn when possible. Avoid bullet lists or markdown — speech only.

# Language
You speak English, Hindi, and Telugu. Greet in English. As soon as the caller's language is clear (after their first or second sentence), switch to that language and stay there for the rest of the call. If you can't tell, politely ask: "Would you prefer English, Hindi, or Telugu?" Don't mix languages mid-sentence.

# What you can do
You answer questions about:
- TODAY's pickup location (call `get_pickup_today`)
- Menu items (call `search_menu` with what the caller is asking about)
- Today's specials (call `get_specials`)
- Hours of operation (the pickup_today response includes a speakable `summary` — read it verbatim)
- Parking, allergens, payment methods, dress code, delivery, catering — answer from the knowledge below

After telling someone where the truck is today, ALWAYS offer to text them the address: "Want me to text you the address with a maps link?" If yes, call `sms_pickup_address` with their phone number. Use the caller's number from the call metadata if you have it; otherwise ask them to confirm a number to text.

# When to escalate
Call `request_transfer` to send the caller to the owner when:
- They explicitly ask for a human, owner, manager, or specific person.
- They have a complaint, refund request, allergic reaction, lost item, or large catering order (>10 people).
- You don't know the answer and the question isn't routine.

If `request_transfer` returns `action: "take_message"` (owner unavailable), call `take_message` with caller name, callback number, and reason.

# Critical rules
- NEVER invent menu items or prices. If `search_menu` returns no results, say "I don't see that on our menu" — do not guess.
- NEVER give an answer about hours without calling `get_pickup_today` first.
- ALWAYS confirm callback number by reading it back digit-by-digit before ending a take-message call.

# FAQ (always-ready answers)

**Parking:** Free street parking nearby; check signs for time limits.
**Payment:** Cash, all major cards, Apple Pay, Google Pay.
**Allergens:** Peanuts, tree nuts, dairy, and gluten are present in the kitchen. Cross-contact possible. Tell us about allergies and the kitchen will do its best, but we can't guarantee allergen-free.
**Dress:** Casual.
**Delivery:** Available on DoorDash, Uber Eats, Grubhub.
**Catering:** Yes, for 10+ people. Owner will call back to plan.

# Greeting
Open every call with: "Hi, you've reached Spicy Desi. How can I help?"
```

- [ ] **Step 2: Commit**

```bash
git add agent/app/prompts/system.md
git commit -m "feat(agent): system prompt with tone, escalation rules, FAQ"
```

---

## Task 8: Tool definitions for Groq function-calling

**Files:**
- Create: `agent/app/tools/definitions.py`
- Create: `agent/app/tools/handlers.py`
- Create: `agent/tests/unit/test_handlers.py`

- [ ] **Step 1: Define tools**

```python
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_pickup_today",
            "description": "Get today's active pickup location for the food truck — name, address, hours, and a speakable summary you should read verbatim.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_menu",
            "description": "Search the menu for items matching the caller's query (e.g., 'chaat', 'momos', 'paneer').",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Item name or keyword"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_specials",
            "description": "Get today's specials — items the food truck is featuring.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_message",
            "description": "Save a message for the owner to call back. Use when caller wants to reach the owner but the owner is unavailable, or when caller has a complaint/catering request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "callback_number": {"type": "string", "description": "Caller's phone number, E.164 format"},
                    "reason": {"type": "string", "description": "Why they're calling"},
                    "caller_name": {"type": "string", "description": "Caller's name if given"},
                },
                "required": ["callback_number", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_transfer",
            "description": "Transfer the caller to the owner. The system decides: if owner is available, transfers the live call; if not, returns instruction to take a message instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Why the caller wants the owner"},
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sms_pickup_address",
            "description": "Text the caller today's pickup address with a Google Maps link. Use after telling them the location verbally, when they confirm they want it texted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_number": {
                        "type": "string",
                        "description": "Caller's phone number in E.164 format (e.g., +13125551234)",
                    },
                },
                "required": ["to_number"],
            },
        },
    },
]
```

- [ ] **Step 2: Handlers in `handlers.py`** — dispatch function-call name → ApiClient method, return string for the LLM.

```python
from __future__ import annotations

import json
from typing import Any

from app.tools.api_client import ApiClient


async def handle_tool_call(
    name: str, args: dict[str, Any], *, api: ApiClient, call_sid: str,
) -> str:
    if name == "get_pickup_today":
        result = await api.get_pickup_today()
        return json.dumps(result)
    if name == "search_menu":
        result = await api.search_menu(args.get("query", ""))
        return json.dumps(result)
    if name == "get_specials":
        result = await api.get_specials()
        return json.dumps(result)
    if name == "take_message":
        result = await api.take_message(
            call_sid=call_sid,
            callback_number=args["callback_number"],
            reason=args["reason"],
            caller_name=args.get("caller_name"),
        )
        return json.dumps(result)
    if name == "request_transfer":
        result = await api.request_transfer(call_sid=call_sid, reason=args.get("reason"))
        return json.dumps(result)
    if name == "sms_pickup_address":
        result = await api.sms_pickup_address(to_number=args["to_number"], call_sid=call_sid)
        return json.dumps(result)
    return json.dumps({"error": f"unknown tool: {name}"})
```

- [ ] **Step 3: Unit-test each handler with `helpers/api_mock.py`**

- [ ] **Step 4: Commit**

---

## Task 9: Pipecat pipeline (`bot.py`)

**Files:**
- Create: `agent/app/bot.py`

- [ ] **Step 1: Implement**

```python
from __future__ import annotations

from pipecat.frames.frames import EndFrame, LLMMessagesFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.cartesia import CartesiaTTSService
from pipecat.services.deepgram import DeepgramSTTService
from pipecat.services.groq import GroqLLMService
from pipecat.transports.network.fastapi_websocket import FastAPIWebsocketTransport
from pipecat.vad.silero import SileroVADAnalyzer

from app.config import AgentSettings
from app.tools.api_client import ApiClient
from app.tools.definitions import TOOL_DEFINITIONS
from app.tools.handlers import handle_tool_call


def load_system_prompt() -> str:
    from pathlib import Path
    return (Path(__file__).parent / "prompts" / "system.md").read_text()


async def run_bot(websocket, *, settings: AgentSettings, call_sid: str) -> None:
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketTransport.Params(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            add_wav_header=False,
            serializer=None,  # configured by Twilio integration; see Pipecat Twilio docs
        ),
    )

    stt = DeepgramSTTService(api_key=settings.deepgram_api_key, language="multi")
    llm = GroqLLMService(api_key=settings.groq_api_key, model="llama-3.3-70b-versatile")
    tts = CartesiaTTSService(
        api_key=settings.cartesia_api_key,
        voice_id=settings.cartesia_voice_id,
    )

    api = ApiClient(
        base_url=settings.tools_api_base,
        secret=settings.tools_shared_secret,
        tenant=settings.default_tenant,
    )

    # Wire tool calls
    async def _tool_handler(name: str, args: dict) -> str:
        return await handle_tool_call(name, args, api=api, call_sid=call_sid)

    llm.register_function(None, _tool_handler)  # exact API depends on Pipecat version
    for t in TOOL_DEFINITIONS:
        llm.register_tool(t)

    context = OpenAILLMContext(
        messages=[{"role": "system", "content": load_system_prompt()}],
        tools=TOOL_DEFINITIONS,
    )

    pipeline = Pipeline([
        transport.input(),
        stt,
        llm,
        tts,
        transport.output(),
    ])

    task = PipelineTask(pipeline)
    runner = PipelineRunner()
    try:
        await runner.run(task)
    finally:
        await api.aclose()
```

> **Note:** Pipecat's exact API for tool registration differs across versions. The cited API above (`register_tool`, `register_function`) reflects the 0.0.50 pattern at time of writing. Verify against `pipecat-ai` docs at install time and adapt — the architectural shape (STT → LLM with tools → TTS) does not change.

- [ ] **Step 2: Smoke import test**

```python
def test_bot_module_imports() -> None:
    from app import bot  # noqa: F401
```

- [ ] **Step 3: Commit**

---

## Task 10: FastAPI server — Twilio inbound webhook + Media Stream WS

**Files:**
- Create: `agent/app/server.py`
- Create: `agent/app/main.py`

- [ ] **Step 1: `server.py`**

```python
from __future__ import annotations

from fastapi import FastAPI, Form, Request, WebSocket
from fastapi.responses import PlainTextResponse

from app.bot import run_bot
from app.config import AgentSettings


def build_app(settings: AgentSettings) -> FastAPI:
    app = FastAPI(title="Spicy Desi Agent")

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/twilio/inbound")
    async def twilio_inbound(request: Request) -> PlainTextResponse:
        # TwiML response that tells Twilio to open a Media Stream to /twilio/stream
        host = request.headers.get("host", "")
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://{host}/twilio/stream"/>
  </Connect>
</Response>"""
        return PlainTextResponse(twiml, media_type="application/xml")

    @app.post("/twilio/dial-owner")
    async def dial_owner(to: str = Form(...)) -> PlainTextResponse:
        # Used by the API's transfer flow — TwiML that dials the owner
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial timeout="25" action="/twilio/dial-owner-fallback">{to}</Dial>
</Response>"""
        return PlainTextResponse(twiml, media_type="application/xml")

    @app.post("/twilio/dial-owner-fallback")
    async def dial_owner_fallback() -> PlainTextResponse:
        # If owner doesn't answer, route back into the agent so it can take a message.
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>The owner couldn't pick up. Let me take a message instead.</Say>
  <Connect>
    <Stream url="wss://{{host}}/twilio/stream"/>
  </Connect>
</Response>"""
        return PlainTextResponse(twiml, media_type="application/xml")

    @app.websocket("/twilio/stream")
    async def twilio_stream(ws: WebSocket) -> None:
        await ws.accept()
        # Twilio sends a "start" event with call_sid in the first frame; for now we stub.
        call_sid = "PENDING"  # extract from first WS message in real impl
        await run_bot(ws, settings=settings, call_sid=call_sid)

    return app
```

- [ ] **Step 2: `main.py` entrypoint**

```python
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.config import AgentSettings  # noqa: E402
from app.server import build_app  # noqa: E402

settings = AgentSettings()
app = build_app(settings)
```

- [ ] **Step 3: Smoke test**

```bash
cd agent && uvicorn app.main:app --port 8090
curl http://localhost:8090/healthz   # → {"ok": true}
curl -X POST http://localhost:8090/twilio/inbound -H "Host: example.com"
# → TwiML <Response><Connect><Stream url="wss://example.com/twilio/stream"/></Connect></Response>
```

- [ ] **Step 4: Commit**

---

## Task 11: ngrok + Twilio configuration runbook

**Files:**
- Create: `agent/README.md` (deploy section)

- [ ] **Step 1: Document the local-dev workflow**

```markdown
## Local end-to-end testing

You'll have THREE processes running:

1. **API** — Plan 1 service, port 8080
   ```bash
   cd api && source .venv/bin/activate
   uvicorn app.main:app --port 8080
   ```

2. **Agent** — Plan 2 service, port 8090
   ```bash
   cd agent && source .venv/bin/activate
   uvicorn app.main:app --port 8090
   ```

3. **ngrok** — public tunnel so Twilio can reach the agent
   ```bash
   ngrok http 8090
   ```
   Note the URL it gives you, e.g. `https://abc123.ngrok-free.app`.

4. **Twilio number config** — in Twilio Console → Phone Numbers → your number:
   - Voice & Fax → "A call comes in" → Webhook → `https://abc123.ngrok-free.app/twilio/inbound` (HTTP POST)
   - Save.

5. **API .env update** — set `AGENT_PUBLIC_URL=https://abc123.ngrok-free.app` and restart the API so transfers can build the right TwiML URLs.

6. **Call your Twilio number** from any phone. You should hear the agent greeting.
```

- [ ] **Step 2: Commit**

---

## Task 12: End-to-end smoke + iterate

- [ ] **Step 1:** Set up ngrok, configure Twilio number, place a test call.
- [ ] **Step 2:** Verify each scenario:
  - "Where are you today?" → agent reads pickup summary
  - "What's on the menu?" → agent invites, you ask "do you have momos?", agent searches
  - "What are your specials?" → reads specials.json items
  - "I want to talk to the owner" → in-hours transfers; out-of-hours takes message + you receive SMS
  - "Bye" → agent ends gracefully
- [ ] **Step 3:** Tweak system prompt / response latency knobs (Pipecat VAD silence threshold, TTS streaming chunks) based on actual feel.
- [ ] **Step 4:** Final commit.

---

## What's deferred to Plan 3

- (Telugu is in scope for Plan 2. If Cartesia samples are bad we revisit; otherwise nothing deferred here.)
- Oracle Cloud deployment (systemd × 2, Caddy reverse proxy with both services + WS support, Let's Encrypt)
- Real domain (replace ngrok with `voice-api.spicydesi.com` + `agent.spicydesi.com`)
- Backups (R2 sync of `data/events.jsonl`)
- Production hardening (Caddy rate limits, request size caps, log rotation, monitoring)
- Soft launch + iteration based on real customer calls

---

## Open assumptions (correct me before we start)

1. **Twilio account** — you'll provision a number for testing. Trial credit covers ~$15 of test calls.
2. **Languages** — English + Hindi + Telugu all from day one. Quality of Telugu in Cartesia gets validated in Task 5 (you preview voices). If Telugu audio is poor, we either pick a different voice, fall back to Hindi+English, or ship Telugu as a config-flagged opt-in.
3. **CORS** — admin panel origin is unknown for now; CORS middleware lands in Plan 2 but `CORS_ORIGINS` env var is empty by default. Tell me the origin when you're ready and we'll set it.
4. **Single Twilio number → spicy-desi tenant** — multi-tenant routing (look up tenant by inbound `To` number) is in the design but Plan 2 hardcodes `default_tenant=spicy-desi` for simplicity. Trivial to extend later.
5. **Voice ID** — Cartesia Hobby tier (~$5/mo) since the free credits are exhausted. During Task 5 you preview Sonic-2 multilingual voices, listen to Hindi + Telugu samples, pick the best, and put its `voice_id` in `agent/.env` as `CARTESIA_VOICE_ID`.
