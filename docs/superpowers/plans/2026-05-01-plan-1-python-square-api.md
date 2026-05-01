# Plan 1 — Python FastAPI Square-backed API (no DB)

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a FastAPI service that exposes Square-backed read endpoints (locations, hours, menu, specials, address) plus skeleton write endpoints for the voice agent (`/api/messages`, `/api/transfers`, `/api/calls/{sid}/event`). End state: a fully tested, signed-secret-protected API that a Pipecat voice agent can call. Stateless except for an optional JSONL audit log.

**Architecture:** N-tier (Hexagonal) with strict layer rules. Pure stdlib for persistence (JSONL append). In-memory TTL cache for Square responses, invalidated by Square's `catalog.version.updated` webhook. Multi-tenant ready via per-tenant config files. Deployed via systemd + Caddy on Oracle Cloud Free Tier ARM.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, Pydantic v2 (+ pydantic-settings), `square` (official SDK), `httpx`, `structlog`, pytest + pytest-asyncio + httpx test client, ruff (lint+format), mypy (strict).

---

## Layer rules (N-tier / Hexagonal)

Dependencies flow **inward only**:

```
api → services → infrastructure
       ↓
     domain (no deps)
```

- `app/api/routes/`        — HTTP handlers; depend on `services/` only via FastAPI Depends
- `app/services/`          — business logic; depend on `infrastructure/` and `domain/`
- `app/infrastructure/`    — adapters (Square, cache, config, logger, tenant registry, event log)
- `app/domain/`            — Pydantic models, enums, value objects (zero deps)
- A `services/` function never imports a route. A `domain/` model never imports anything from the project.

Tests:
- `tests/unit/`        — services and infrastructure with mocked adapters; no HTTP
- `tests/integration/` — full app via FastAPI `TestClient` with mocked Square SDK

---

## Phase 0 — accounts (offline-friendly tasks below don't require any of these)

- [ ] **Square Sandbox** — Square Developer Dashboard → create Application → grab Sandbox access token. Add scopes `MERCHANT_PROFILE_READ`, `ITEMS_READ`. Note `merchant_id`. (Optional now, required for Task 21 smoke test against real Square.)
- [ ] **Square production token** — same flow, when you go live.
- [ ] **"Specials" category** — in Square Dashboard, create or rename a category to `Specials` and tag a couple of items.
- [ ] **Twilio, Groq, Deepgram, Cartesia, Oracle, domain** — needed for Plan 2/Plan 3, not Plan 1.

---

## File Structure

```
api/
  pyproject.toml
  README.md
  .python-version
  .env.example
  app/
    __init__.py
    main.py                                # ASGI entrypoint (uvicorn target)
    api/
      __init__.py
      app_factory.py                       # build_app(deps) — wires routes + middleware
      dependencies.py                      # FastAPI Depends: auth, tenant resolution, services
      routes/
        __init__.py
        health.py
        locations.py
        hours.py
        address.py
        menu.py
        specials.py
        messages.py
        transfers.py
        events.py
        webhooks_square.py
    services/
      __init__.py
      locations_service.py                 # business logic on top of Square locations
      catalog_service.py                   # business logic on top of Square catalog
      transfer_decision_service.py         # owner-available-hours rule
    domain/
      __init__.py
      models.py                            # Pydantic: Tenant, LocationListItem, HoursToday,
                                           # AddressInfo, MenuItem, MessageRequest,
                                           # TransferRequest, EventRecord
    infrastructure/
      __init__.py
      config.py                            # AppSettings (pydantic-settings)
      logger.py                            # structlog setup
      cache.py                             # TtlCache
      square_client.py                     # SquareClientFactory + protocols
      tenant_registry.py                   # load_tenants + lookup_by_twilio_number
      event_log.py                         # JsonlEventLog: append + iterate
  tests/
    __init__.py
    conftest.py                            # shared fixtures: app factory, mock Square, tmp configs
    helpers/
      __init__.py
      square_mock.py
    unit/
      __init__.py
      test_config.py
      test_tenant_registry.py
      test_cache.py
      test_locations_service.py
      test_catalog_service.py
      test_transfer_decision_service.py
      test_event_log.py
    integration/
      __init__.py
      test_health.py
      test_auth.py
      test_locations_route.py
      test_hours_route.py
      test_address_route.py
      test_menu_route.py
      test_specials_route.py
      test_messages_route.py
      test_transfers_route.py
      test_events_route.py
      test_square_webhook.py
configs/
  index.json
  spicy-desi/
    tenant.json
    faq.md
    location-notes.md
deploy/
  voice-api.service
  Caddyfile
  README-deploy.md
```

---

## Task 1: Python project scaffold

**Files:**
- Create: `api/pyproject.toml`
- Create: `api/.python-version`
- Create: `api/.env.example`
- Create: `api/README.md`

- [ ] **Step 1: Create `api/pyproject.toml`**

```toml
[project]
name = "spicy-desi-api"
version = "0.1.0"
description = "Spicy Desi voice-agent API"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.32.0",
  "pydantic>=2.9.0",
  "pydantic-settings>=2.6.0",
  "structlog>=24.4.0",
  "httpx>=0.27.0",
  "squareup>=39.0.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3.0",
  "pytest-asyncio>=0.24.0",
  "ruff>=0.7.0",
  "mypy>=1.13.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "N", "SIM", "RUF"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_ignores = true

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]
```

- [ ] **Step 2: Create `api/.python-version`**

```
3.11
```

- [ ] **Step 3: Create `api/.env.example`**

```
PORT=8080
LOG_LEVEL=info
APP_ENV=development

TOOLS_SHARED_SECRET=replace-with-long-random-string-min-32-chars

SQUARE_ACCESS_TOKEN=
SQUARE_ENVIRONMENT=sandbox
SQUARE_WEBHOOK_SIGNATURE_KEY=
SQUARE_WEBHOOK_URL=

CONFIGS_DIR=../configs

EVENT_LOG_PATH=./data/events.jsonl
```

- [ ] **Step 4: Create `api/README.md`**

```markdown
# Spicy Desi API

FastAPI service exposing Square-backed endpoints for the Pipecat voice agent.

## Quick start

    cd api
    python3.11 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"
    cp .env.example .env  # fill in keys
    uvicorn app.main:app --reload --port 8080

## Tests

    pytest

## Lint + typecheck

    ruff check .
    ruff format --check .
    mypy app
```

- [ ] **Step 5: Create venv and install**

```bash
cd api
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: install succeeds.

- [ ] **Step 6: Commit**

```bash
git add api/pyproject.toml api/.python-version api/.env.example api/README.md
git commit -m "chore(api): scaffold FastAPI Python project"
```

---

## Task 2: Domain models (Pydantic)

The `domain/` layer is shared by services and routes. Defining all models upfront keeps later tasks short.

**Files:**
- Create: `api/app/__init__.py` (empty)
- Create: `api/app/domain/__init__.py` (empty)
- Create: `api/app/domain/models.py`
- Create: `api/tests/__init__.py` (empty)
- Create: `api/tests/unit/__init__.py` (empty)
- Create: `api/tests/unit/test_domain_models.py`

- [ ] **Step 1: Write the failing test**

`api/tests/unit/test_domain_models.py`:

```python
import pytest
from pydantic import ValidationError

from app.domain.models import (
    HoursStatus, HoursToday, LocationListItem, MenuItem,
    MessageRequest, TransferRequest, EventRecord, Tenant, OwnerAvailable,
)


def test_hours_today_accepts_valid_status():
    h = HoursToday(open="11:00", close="21:30", status=HoursStatus.OPEN)
    assert h.status == HoursStatus.OPEN


def test_hours_today_allows_null_open_close_when_closed():
    h = HoursToday(open=None, close=None, status=HoursStatus.CLOSED)
    assert h.open is None


def test_message_request_requires_callback_number():
    with pytest.raises(ValidationError):
        MessageRequest(call_sid="CA1", reason="hi")  # type: ignore[call-arg]


def test_tenant_round_trip():
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


def test_event_record_serializes():
    e = EventRecord(call_sid="CA1", kind="message_taken", payload={"caller": "Asha"})
    assert e.model_dump()["kind"] == "message_taken"
```

- [ ] **Step 2: Run failing**

```bash
pytest tests/unit/test_domain_models.py
```

Expected: ImportError.

- [ ] **Step 3: Implement `api/app/domain/models.py`**

```python
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HoursStatus(str, Enum):
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
    action: str  # "transfer" | "take_message"
    target: str | None = None


class EventRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    call_sid: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: float | None = None  # set on append


class OwnerAvailable(BaseModel):
    tz: str
    weekly: dict[str, tuple[str, str]]  # "mon" -> ("11:00", "21:30")


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
```

- [ ] **Step 4: Run passing**

```bash
pytest tests/unit/test_domain_models.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add api/app/__init__.py api/app/domain/ api/tests/__init__.py api/tests/unit/__init__.py api/tests/unit/test_domain_models.py
git commit -m "feat(api): domain models (Pydantic)"
```

---

## Task 3: Config (pydantic-settings)

**Files:**
- Create: `api/app/infrastructure/__init__.py` (empty)
- Create: `api/app/infrastructure/config.py`
- Create: `api/tests/unit/test_config.py`

- [ ] **Step 1: Write failing test**

`api/tests/unit/test_config.py`:

```python
import pytest
from pydantic import ValidationError

from app.infrastructure.config import AppSettings


BASE_ENV = {
    "PORT": "8080",
    "LOG_LEVEL": "info",
    "APP_ENV": "test",
    "TOOLS_SHARED_SECRET": "x" * 32,
    "SQUARE_ACCESS_TOKEN": "tok",
    "SQUARE_ENVIRONMENT": "sandbox",
    "SQUARE_WEBHOOK_SIGNATURE_KEY": "sig",
    "SQUARE_WEBHOOK_URL": "https://example.com",
    "CONFIGS_DIR": "./configs",
    "EVENT_LOG_PATH": "./data/events.jsonl",
}


def test_loads_valid_env(monkeypatch):
    for k, v in BASE_ENV.items():
        monkeypatch.setenv(k, v)
    s = AppSettings()
    assert s.port == 8080
    assert s.square_environment == "sandbox"
    assert s.tools_shared_secret == "x" * 32


def test_rejects_short_secret(monkeypatch):
    env = BASE_ENV | {"TOOLS_SHARED_SECRET": "short"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ValidationError):
        AppSettings()


def test_rejects_invalid_env_value(monkeypatch):
    env = BASE_ENV | {"SQUARE_ENVIRONMENT": "moon"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ValidationError):
        AppSettings()
```

- [ ] **Step 2: Run failing**

```bash
pytest tests/unit/test_config.py
```

- [ ] **Step 3: Implement `api/app/infrastructure/config.py`**

```python
from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,  # tests inject via monkeypatch; main.py loads dotenv before construct
        case_sensitive=False,
        extra="ignore",
    )

    port: int = Field(8080, alias="PORT")
    log_level: str = Field("info", alias="LOG_LEVEL")
    app_env: Literal["development", "test", "production"] = Field("development", alias="APP_ENV")

    tools_shared_secret: str = Field(..., alias="TOOLS_SHARED_SECRET", min_length=32)

    square_access_token: str = Field(..., alias="SQUARE_ACCESS_TOKEN", min_length=1)
    square_environment: Literal["sandbox", "production"] = Field(..., alias="SQUARE_ENVIRONMENT")
    square_webhook_signature_key: str = Field(..., alias="SQUARE_WEBHOOK_SIGNATURE_KEY", min_length=1)
    square_webhook_url: str = Field("", alias="SQUARE_WEBHOOK_URL")

    configs_dir: str = Field(..., alias="CONFIGS_DIR", min_length=1)
    event_log_path: str = Field("./data/events.jsonl", alias="EVENT_LOG_PATH")
```

- [ ] **Step 4: Run passing**

```bash
pytest tests/unit/test_config.py -v
```

- [ ] **Step 5: Commit**

```bash
git add api/app/infrastructure/__init__.py api/app/infrastructure/config.py api/tests/unit/test_config.py
git commit -m "feat(api): AppSettings via pydantic-settings"
```

---

## Task 4: Tenant registry + spicy-desi seed

**Files:**
- Create: `api/app/infrastructure/tenant_registry.py`
- Create: `api/tests/unit/test_tenant_registry.py`
- Create: `configs/index.json`
- Create: `configs/spicy-desi/tenant.json`
- Create: `configs/spicy-desi/faq.md`
- Create: `configs/spicy-desi/location-notes.md`

- [ ] **Step 1: Seed configs**

`configs/index.json`:

```json
{
  "tenants_by_twilio_number": {
    "+15555550100": "spicy-desi"
  }
}
```

`configs/spicy-desi/tenant.json`:

```json
{
  "slug": "spicy-desi",
  "name": "Spicy Desi",
  "twilio_number": "+15555550100",
  "owner_phone": "+15555550199",
  "owner_available": {
    "tz": "America/Chicago",
    "weekly": {
      "mon": ["11:00", "21:30"],
      "tue": ["11:00", "21:30"],
      "wed": ["11:00", "21:30"],
      "thu": ["11:00", "21:30"],
      "fri": ["11:00", "22:30"],
      "sat": ["11:00", "22:30"],
      "sun": ["12:00", "21:00"]
    }
  },
  "square_merchant_id": "REPLACE_ME",
  "languages": ["en", "hi", "te"],
  "sms_confirmation_to_caller": true,
  "location_overrides": {}
}
```

`configs/spicy-desi/faq.md`:

```markdown
# Spicy Desi — FAQ

## Parking
Free street parking nearby; check signs for time limits.

## Payment methods
Cash, Visa, Mastercard, AmEx, Discover, Apple Pay, Google Pay.

## Allergens
Peanuts, tree nuts, dairy, and gluten are present in the kitchen. Cross-contact is possible. Tell us about allergies when ordering and the kitchen will do its best, but we cannot guarantee allergen-free preparation.

## Dress code
Casual.

## Delivery
Available on DoorDash, Uber Eats, and Grubhub.

## Catering
We do catering for parties of 10 or more. The owner will call you back to plan it.
```

`configs/spicy-desi/location-notes.md`:

```markdown
# Spicy Desi — Per-location notes

Keyed by Square location_id.

## REPLACE_WITH_LOCATION_ID
Cross street: TBD
Parking: TBD
Public transit: TBD
```

- [ ] **Step 2: Write failing test**

`api/tests/unit/test_tenant_registry.py`:

```python
import json
from pathlib import Path

import pytest

from app.infrastructure.tenant_registry import (
    TenantRegistry, load_tenants, lookup_tenant_by_twilio_number,
)


@pytest.fixture
def configs_dir(tmp_path: Path) -> Path:
    (tmp_path / "index.json").write_text(json.dumps({
        "tenants_by_twilio_number": {"+15555550100": "spicy-desi"},
    }))
    sd = tmp_path / "spicy-desi"
    sd.mkdir()
    (sd / "tenant.json").write_text(json.dumps({
        "slug": "spicy-desi",
        "name": "Spicy Desi",
        "twilio_number": "+15555550100",
        "owner_phone": "+15555550199",
        "owner_available": {"tz": "America/Chicago", "weekly": {"mon": ["11:00", "21:30"]}},
        "square_merchant_id": "M1",
        "languages": ["en"],
        "sms_confirmation_to_caller": True,
        "location_overrides": {},
    }))
    (sd / "faq.md").write_text("# FAQ")
    (sd / "location-notes.md").write_text("# Loc")
    return tmp_path


def test_load_tenants(configs_dir: Path) -> None:
    reg = load_tenants(str(configs_dir))
    assert "spicy-desi" in reg.tenants
    assert reg.tenants["spicy-desi"].name == "Spicy Desi"
    assert reg.tenants["spicy-desi"].faq.startswith("# FAQ")


def test_lookup_by_twilio_number(configs_dir: Path) -> None:
    reg = load_tenants(str(configs_dir))
    t = lookup_tenant_by_twilio_number(reg, "+15555550100")
    assert t is not None and t.slug == "spicy-desi"


def test_lookup_unknown_returns_none(configs_dir: Path) -> None:
    reg = load_tenants(str(configs_dir))
    assert lookup_tenant_by_twilio_number(reg, "+19999999999") is None
```

- [ ] **Step 3: Run failing**

```bash
pytest tests/unit/test_tenant_registry.py
```

- [ ] **Step 4: Implement `api/app/infrastructure/tenant_registry.py`**

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.domain.models import OwnerAvailable, Tenant


@dataclass(frozen=True)
class TenantRegistry:
    tenants: dict[str, Tenant]
    by_twilio_number: dict[str, str]


def load_tenants(configs_dir: str) -> TenantRegistry:
    base = Path(configs_dir)
    index = json.loads((base / "index.json").read_text())
    tenants: dict[str, Tenant] = {}
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        tj = json.loads((entry / "tenant.json").read_text())
        weekly_raw = tj["owner_available"]["weekly"]
        weekly: dict[str, tuple[str, str]] = {
            day: (window[0], window[1]) for day, window in weekly_raw.items()
        }
        tenants[tj["slug"]] = Tenant(
            slug=tj["slug"],
            name=tj["name"],
            twilio_number=tj["twilio_number"],
            owner_phone=tj["owner_phone"],
            owner_available=OwnerAvailable(tz=tj["owner_available"]["tz"], weekly=weekly),
            square_merchant_id=tj["square_merchant_id"],
            languages=tj["languages"],
            sms_confirmation_to_caller=tj["sms_confirmation_to_caller"],
            location_overrides=tj.get("location_overrides", {}),
            faq=(entry / "faq.md").read_text(),
            location_notes=(entry / "location-notes.md").read_text(),
        )
    return TenantRegistry(tenants=tenants, by_twilio_number=index["tenants_by_twilio_number"])


def lookup_tenant_by_twilio_number(reg: TenantRegistry, number: str) -> Tenant | None:
    slug = reg.by_twilio_number.get(number)
    return reg.tenants.get(slug) if slug else None
```

- [ ] **Step 5: Run passing**

```bash
pytest tests/unit/test_tenant_registry.py -v
```

- [ ] **Step 6: Commit**

```bash
git add api/app/infrastructure/tenant_registry.py api/tests/unit/test_tenant_registry.py configs/
git commit -m "feat(api): tenant registry + spicy-desi seed"
```

---

## Task 5: TTL cache

**Files:**
- Create: `api/app/infrastructure/cache.py`
- Create: `api/tests/unit/test_cache.py`

- [ ] **Step 1: Write failing test**

`api/tests/unit/test_cache.py`:

```python
import time
from app.infrastructure.cache import TtlCache


async def test_returns_cached_within_ttl():
    cache: TtlCache[str] = TtlCache(ttl_seconds=10)
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        return "v1"

    assert await cache.get_or_load("k", loader) == "v1"
    assert await cache.get_or_load("k", loader) == "v1"
    assert calls == 1


async def test_reloads_after_expiry():
    cache: TtlCache[str] = TtlCache(ttl_seconds=0.01)
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        return f"v{calls}"

    await cache.get_or_load("k", loader)
    time.sleep(0.05)
    assert await cache.get_or_load("k", loader) == "v2"


async def test_invalidate_one_key():
    cache: TtlCache[str] = TtlCache(ttl_seconds=10)
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        return f"v{calls}"

    await cache.get_or_load("k", loader)
    cache.invalidate("k")
    await cache.get_or_load("k", loader)
    assert calls == 2


async def test_clear_all():
    cache: TtlCache[str] = TtlCache(ttl_seconds=10)
    calls = 0

    async def loader_a() -> str:
        nonlocal calls
        calls += 1
        return "a"

    async def loader_b() -> str:
        nonlocal calls
        calls += 1
        return "b"

    await cache.get_or_load("a", loader_a)
    await cache.get_or_load("b", loader_b)
    cache.clear()
    await cache.get_or_load("a", loader_a)
    assert calls == 3
```

- [ ] **Step 2: Implement `api/app/infrastructure/cache.py`**

```python
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class TtlCache(Generic[T]):
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, _Entry[T]] = {}

    async def get_or_load(self, key: str, loader: Callable[[], Awaitable[T]]) -> T:
        now = time.monotonic()
        hit = self._store.get(key)
        if hit is not None and hit.expires_at > now:
            return hit.value
        value = await loader()
        self._store[key] = _Entry(value=value, expires_at=now + self._ttl)
        return value

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/unit/test_cache.py -v
git add api/app/infrastructure/cache.py api/tests/unit/test_cache.py
git commit -m "feat(api): TTL cache for Square responses"
```

---

## Task 6: Square client wrapper + protocols

**Files:**
- Create: `api/app/infrastructure/square_client.py`
- Create: `api/tests/helpers/__init__.py` (empty)
- Create: `api/tests/helpers/square_mock.py`

- [ ] **Step 1: Implement `api/app/infrastructure/square_client.py`**

We define narrow Protocol types so services depend on interfaces, not the SDK. The wrapper translates the official SDK to those interfaces.

```python
from __future__ import annotations

from typing import Any, Protocol

from square.client import Client


class LocationsApi(Protocol):
    async def list_locations(self) -> list[dict[str, Any]]: ...
    async def retrieve_location(self, location_id: str) -> dict[str, Any] | None: ...


class CatalogApi(Protocol):
    async def search_items(
        self, *, text_filter: str | None = None, category_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...


def make_square_client(*, access_token: str, environment: str) -> Client:
    return Client(access_token=access_token, environment=environment)


class SquareLocationsAdapter:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def list_locations(self) -> list[dict[str, Any]]:
        result = self._client.locations.list_locations()
        if result.is_error():
            raise RuntimeError(f"square list_locations error: {result.errors}")
        return result.body.get("locations", [])

    async def retrieve_location(self, location_id: str) -> dict[str, Any] | None:
        result = self._client.locations.retrieve_location(location_id=location_id)
        if result.is_error():
            return None
        return result.body.get("location")


class SquareCatalogAdapter:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def search_items(
        self, *, text_filter: str | None = None, category_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {}
        if text_filter:
            body["text_filter"] = text_filter
        if category_ids:
            body["category_ids"] = category_ids
        result = self._client.catalog.search_catalog_items(body=body)
        if result.is_error():
            raise RuntimeError(f"square search_catalog_items error: {result.errors}")
        return result.body.get("items", [])
```

- [ ] **Step 2: Implement test mock**

`api/tests/helpers/square_mock.py`:

```python
from __future__ import annotations

from typing import Any


class FakeLocationsApi:
    def __init__(self, locations: list[dict[str, Any]]) -> None:
        self._locations = locations

    async def list_locations(self) -> list[dict[str, Any]]:
        return list(self._locations)

    async def retrieve_location(self, location_id: str) -> dict[str, Any] | None:
        for loc in self._locations:
            if loc["id"] == location_id:
                return loc
        return None


class FakeCatalogApi:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    async def search_items(
        self, *, text_filter: str | None = None, category_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        result = list(self._items)
        if text_filter:
            q = text_filter.lower()
            result = [i for i in result if q in i["item_data"]["name"].lower()]
        if category_ids:
            ids = set(category_ids)
            result = [
                i for i in result
                if any(c["id"] in ids for c in i["item_data"].get("categories", []))
            ]
        return result
```

- [ ] **Step 3: Commit (no test yet — exercised in service tests)**

```bash
git add api/app/infrastructure/square_client.py api/tests/helpers/
git commit -m "feat(api): Square SDK wrapper + protocol seams + test mock"
```

---

## Task 7: LocationsService (service layer)

**Files:**
- Create: `api/app/services/__init__.py` (empty)
- Create: `api/app/services/locations_service.py`
- Create: `api/tests/unit/test_locations_service.py`

- [ ] **Step 1: Write failing test**

`api/tests/unit/test_locations_service.py`:

```python
from datetime import datetime, timezone

import pytest

from app.domain.models import HoursStatus
from app.infrastructure.cache import TtlCache
from app.services.locations_service import LocationsService
from tests.helpers.square_mock import FakeLocationsApi


SAMPLE = [
    {
        "id": "L1",
        "name": "Spicy Desi Loop",
        "address": {
            "address_line_1": "111 W Madison",
            "locality": "Chicago",
            "administrative_district_level_1": "IL",
            "postal_code": "60602",
        },
        "coordinates": {"latitude": 41.881, "longitude": -87.631},
        "business_hours": {"periods": [
            {"day_of_week": "MON", "start_local_time": "11:00:00", "end_local_time": "21:30:00"},
        ]},
        "timezone": "America/Chicago",
    },
]


@pytest.fixture
def svc() -> LocationsService:
    return LocationsService(api=FakeLocationsApi(SAMPLE), cache=TtlCache(ttl_seconds=60))


async def test_list_locations(svc: LocationsService) -> None:
    out = await svc.list_locations()
    assert len(out) == 1
    assert out[0].location_id == "L1"
    assert "Madison" in out[0].address


async def test_hours_today_open_at_2pm_monday(svc: LocationsService) -> None:
    monday2pm = datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc)  # 14:00 Chicago
    h = await svc.get_hours_today("L1", now=monday2pm)
    assert h.open == "11:00"
    assert h.close == "21:30"
    assert h.status == HoursStatus.OPEN


async def test_hours_today_closed_early_morning(svc: LocationsService) -> None:
    monday6am = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)  # 06:00 Chicago
    h = await svc.get_hours_today("L1", now=monday6am)
    assert h.status == HoursStatus.CLOSED


async def test_address(svc: LocationsService) -> None:
    a = await svc.get_address("L1")
    assert "Madison" in a.formatted
    assert a.lat == pytest.approx(41.881)


async def test_unknown_location_raises(svc: LocationsService) -> None:
    with pytest.raises(KeyError):
        await svc.get_hours_today("Lnope")
```

- [ ] **Step 2: Implement `api/app/services/locations_service.py`**

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.models import AddressInfo, HoursStatus, HoursToday, LocationListItem
from app.infrastructure.cache import TtlCache
from app.infrastructure.square_client import LocationsApi


def _format_address(addr: dict[str, Any] | None) -> str:
    if not addr:
        return ""
    parts = [
        addr.get("address_line_1"),
        addr.get("locality"),
        addr.get("administrative_district_level_1"),
        addr.get("postal_code"),
    ]
    return ", ".join(p for p in parts if p)


def _hhmm(value: str | None) -> str | None:
    return value[:5] if value else None


def _to_minutes(hhmm_str: str) -> int:
    h, m = (int(x) for x in hhmm_str.split(":"))
    return h * 60 + m


class LocationsService:
    def __init__(self, api: LocationsApi, cache: TtlCache[list[dict[str, Any]]]) -> None:
        self._api = api
        self._cache = cache

    async def _all(self) -> list[dict[str, Any]]:
        return await self._cache.get_or_load("all", self._api.list_locations)

    async def list_locations(self) -> list[LocationListItem]:
        return [
            LocationListItem(
                location_id=loc["id"],
                name=loc["name"],
                address=_format_address(loc.get("address")),
            )
            for loc in await self._all()
        ]

    async def get_hours_today(
        self, location_id: str, now: datetime | None = None,
    ) -> HoursToday:
        loc = await self._find(location_id)
        tz = ZoneInfo(loc.get("timezone") or "America/Chicago")
        cur = (now or datetime.now(timezone.utc)).astimezone(tz)
        dow = cur.strftime("%a").upper()  # MON, TUE, ...
        period = next(
            (p for p in loc.get("business_hours", {}).get("periods", []) if p.get("day_of_week") == dow),
            None,
        )
        if period is None:
            return HoursToday(open=None, close=None, status=HoursStatus.CLOSED)
        open_str = _hhmm(period.get("start_local_time"))
        close_str = _hhmm(period.get("end_local_time"))
        cur_str = cur.strftime("%H:%M")
        status = HoursStatus.CLOSED
        if open_str and close_str and open_str <= cur_str < close_str:
            if _to_minutes(close_str) - _to_minutes(cur_str) <= 30:
                status = HoursStatus.CLOSING_SOON
            else:
                status = HoursStatus.OPEN
        return HoursToday(open=open_str, close=close_str, status=status)

    async def get_address(self, location_id: str) -> AddressInfo:
        loc = await self._find(location_id)
        coords = loc.get("coordinates") or {}
        return AddressInfo(
            formatted=_format_address(loc.get("address")),
            lat=coords.get("latitude"),
            lng=coords.get("longitude"),
        )

    async def _find(self, location_id: str) -> dict[str, Any]:
        for loc in await self._all():
            if loc["id"] == location_id:
                return loc
        raise KeyError(f"location not found: {location_id}")
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/unit/test_locations_service.py -v
git add api/app/services/__init__.py api/app/services/locations_service.py api/tests/unit/test_locations_service.py
git commit -m "feat(api): LocationsService — list, hours-today, address"
```

---

## Task 8: CatalogService

**Files:**
- Create: `api/app/services/catalog_service.py`
- Create: `api/tests/unit/test_catalog_service.py`

- [ ] **Step 1: Write failing test**

`api/tests/unit/test_catalog_service.py`:

```python
import pytest

from app.infrastructure.cache import TtlCache
from app.services.catalog_service import CatalogService
from tests.helpers.square_mock import FakeCatalogApi


ITEMS = [
    {
        "id": "I1",
        "type": "ITEM",
        "item_data": {
            "name": "Chicken Tikka Masala",
            "description": "Boneless chicken in creamy tomato sauce",
            "categories": [{"id": "MAINS"}],
            "variations": [{
                "id": "V1",
                "item_variation_data": {"price_money": {"amount": 1899, "currency": "USD"}},
            }],
        },
    },
    {
        "id": "I2",
        "type": "ITEM",
        "item_data": {
            "name": "Paneer Tikka",
            "description": "Grilled paneer cubes",
            "categories": [{"id": "STARTERS"}, {"id": "SPECIALS"}],
            "variations": [{
                "id": "V2",
                "item_variation_data": {"price_money": {"amount": 1599, "currency": "USD"}},
            }],
        },
    },
]


@pytest.fixture
def svc() -> CatalogService:
    return CatalogService(
        api=FakeCatalogApi(ITEMS), cache=TtlCache(ttl_seconds=60), specials_category_id="SPECIALS",
    )


async def test_search_menu_finds_match(svc: CatalogService) -> None:
    r = await svc.search_menu("paneer")
    assert len(r) == 1
    assert r[0].name == "Paneer Tikka"
    assert r[0].price == "$15.99"


async def test_search_menu_no_match(svc: CatalogService) -> None:
    assert await svc.search_menu("sushi") == []


async def test_specials_returns_only_tagged(svc: CatalogService) -> None:
    r = await svc.get_specials()
    assert len(r) == 1
    assert r[0].name == "Paneer Tikka"
```

- [ ] **Step 2: Implement `api/app/services/catalog_service.py`**

```python
from __future__ import annotations

from typing import Any

from app.domain.models import MenuItem
from app.infrastructure.cache import TtlCache
from app.infrastructure.square_client import CatalogApi


def _format_price(amount: int | None, currency: str | None) -> str:
    if amount is None:
        return ""
    value = amount / 100
    if currency == "USD":
        return f"${value:.2f}"
    return f"{value:.2f} {currency or ''}".strip()


def _to_menu_item(raw: dict[str, Any]) -> MenuItem:
    item_data = raw.get("item_data", {})
    variations = item_data.get("variations") or []
    price_money = (
        variations[0].get("item_variation_data", {}).get("price_money", {}) if variations else {}
    )
    categories = item_data.get("categories") or []
    return MenuItem(
        name=item_data.get("name", ""),
        description=item_data.get("description", ""),
        price=_format_price(price_money.get("amount"), price_money.get("currency")),
        category=categories[0]["id"] if categories else None,
        dietary_tags=[],
    )


class CatalogService:
    def __init__(
        self, api: CatalogApi, cache: TtlCache[list[dict[str, Any]]], specials_category_id: str,
    ) -> None:
        self._api = api
        self._cache = cache
        self._specials_id = specials_category_id

    async def search_menu(self, query: str) -> list[MenuItem]:
        items = await self._api.search_items(text_filter=query)
        return [_to_menu_item(i) for i in items]

    async def get_specials(self) -> list[MenuItem]:
        async def loader() -> list[dict[str, Any]]:
            return await self._api.search_items(category_ids=[self._specials_id])

        items = await self._cache.get_or_load("specials", loader)
        return [_to_menu_item(i) for i in items]

    def invalidate(self) -> None:
        self._cache.clear()
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/unit/test_catalog_service.py -v
git add api/app/services/catalog_service.py api/tests/unit/test_catalog_service.py
git commit -m "feat(api): CatalogService — menu search + specials"
```

---

## Task 9: Transfer-decision service

Pure function: given a tenant + current time, decide `transfer` vs `take_message`.

**Files:**
- Create: `api/app/services/transfer_decision_service.py`
- Create: `api/tests/unit/test_transfer_decision_service.py`

- [ ] **Step 1: Failing test**

```python
from datetime import datetime, timezone

from app.domain.models import OwnerAvailable, Tenant
from app.services.transfer_decision_service import decide_transfer


def _tenant() -> Tenant:
    return Tenant(
        slug="spicy-desi", name="Spicy Desi", twilio_number="+15555550100",
        owner_phone="+15555550199",
        owner_available=OwnerAvailable(tz="America/Chicago", weekly={"mon": ("11:00", "21:30")}),
        square_merchant_id="M1", languages=["en"], sms_confirmation_to_caller=True,
        location_overrides={}, faq="", location_notes="",
    )


def test_in_window_returns_transfer():
    monday2pm = datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc)
    d = decide_transfer(_tenant(), now=monday2pm)
    assert d.action == "transfer"
    assert d.target == "+15555550199"


def test_outside_window_returns_take_message():
    monday6am = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    d = decide_transfer(_tenant(), now=monday6am)
    assert d.action == "take_message"


def test_no_window_for_day_returns_take_message():
    sunday = datetime(2026, 1, 4, 18, 0, tzinfo=timezone.utc)  # day with no entry
    d = decide_transfer(_tenant(), now=sunday)
    assert d.action == "take_message"
```

- [ ] **Step 2: Implement `api/app/services/transfer_decision_service.py`**

```python
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.domain.models import Tenant, TransferDecision


def decide_transfer(tenant: Tenant, *, now: datetime | None = None) -> TransferDecision:
    tz = ZoneInfo(tenant.owner_available.tz)
    cur = (now or datetime.now(timezone.utc)).astimezone(tz)
    day_key = cur.strftime("%a").lower()[:3]
    window = tenant.owner_available.weekly.get(day_key)
    if window is None:
        return TransferDecision(action="take_message")
    cur_hhmm = cur.strftime("%H:%M")
    if window[0] <= cur_hhmm < window[1]:
        return TransferDecision(action="transfer", target=tenant.owner_phone)
    return TransferDecision(action="take_message")
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/unit/test_transfer_decision_service.py -v
git add api/app/services/transfer_decision_service.py api/tests/unit/test_transfer_decision_service.py
git commit -m "feat(api): transfer-decision service (owner-hours rule)"
```

---

## Task 10: JSONL event log

**Files:**
- Create: `api/app/infrastructure/event_log.py`
- Create: `api/tests/unit/test_event_log.py`

- [ ] **Step 1: Failing test**

```python
import json
from pathlib import Path

import pytest

from app.domain.models import EventRecord
from app.infrastructure.event_log import JsonlEventLog


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "events.jsonl"


async def test_append_and_iterate(log_path: Path) -> None:
    log = JsonlEventLog(str(log_path))
    await log.append(EventRecord(call_sid="CA1", kind="call_started", payload={}))
    await log.append(EventRecord(call_sid="CA1", kind="message_taken", payload={"name": "Asha"}))

    lines = log_path.read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["call_sid"] == "CA1"
    assert first["kind"] == "call_started"
    assert "ts" in first


async def test_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "sub" / "events.jsonl"
    log = JsonlEventLog(str(nested))
    await log.append(EventRecord(call_sid="CA1", kind="x"))
    assert nested.exists()
```

- [ ] **Step 2: Implement `api/app/infrastructure/event_log.py`**

```python
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from app.domain.models import EventRecord


class JsonlEventLog:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._lock = asyncio.Lock()

    async def append(self, event: EventRecord) -> None:
        record = event.model_copy(update={"ts": event.ts or time.time()})
        line = json.dumps(record.model_dump(), separators=(",", ":")) + "\n"
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line)
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/unit/test_event_log.py -v
git add api/app/infrastructure/event_log.py api/tests/unit/test_event_log.py
git commit -m "feat(api): JSONL event log"
```

---

## Task 11: Logger setup

**Files:**
- Create: `api/app/infrastructure/logger.py`

- [ ] **Step 1: Implement (no test — adapter for structlog)**

```python
from __future__ import annotations

import logging

import structlog


def configure_logging(level: str = "info") -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )


def get_logger(name: str = "api") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
```

- [ ] **Step 2: Commit**

```bash
git add api/app/infrastructure/logger.py
git commit -m "feat(api): structlog config"
```

---

## Task 12: FastAPI app factory + dependencies + auth

**Files:**
- Create: `api/app/api/__init__.py` (empty)
- Create: `api/app/api/dependencies.py`
- Create: `api/app/api/app_factory.py`
- Create: `api/app/api/routes/__init__.py` (empty)
- Create: `api/app/api/routes/health.py`
- Create: `api/tests/integration/__init__.py` (empty)
- Create: `api/tests/conftest.py`
- Create: `api/tests/integration/test_health.py`
- Create: `api/tests/integration/test_auth.py`

- [ ] **Step 1: Implement `api/app/api/dependencies.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, Request, status

from app.infrastructure.event_log import JsonlEventLog
from app.infrastructure.tenant_registry import TenantRegistry
from app.services.catalog_service import CatalogService
from app.services.locations_service import LocationsService


@dataclass
class AppState:
    tools_shared_secret: str
    tenants: TenantRegistry
    locations_service: LocationsService
    catalog_service: CatalogService
    event_log: JsonlEventLog
    square_webhook_signature_key: str
    square_webhook_url: str


def get_state(request: Request) -> AppState:
    return request.app.state.deps  # type: ignore[no-any-return]


def require_tools_auth(
    request: Request,
    x_tools_auth: str | None = Header(default=None),
) -> None:
    expected = get_state(request).tools_shared_secret
    if not x_tools_auth or not _consteq(x_tools_auth, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


def _consteq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode(), strict=False):
        result |= x ^ y
    return result == 0
```

- [ ] **Step 2: Implement `api/app/api/routes/health.py`**

```python
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}
```

- [ ] **Step 3: Implement `api/app/api/app_factory.py`**

```python
from __future__ import annotations

from fastapi import FastAPI

from app.api.dependencies import AppState
from app.api.routes import health


def build_app(deps: AppState) -> FastAPI:
    app = FastAPI(title="Spicy Desi API")
    app.state.deps = deps
    app.include_router(health.router)
    return app
```

- [ ] **Step 4: Implement `api/tests/conftest.py`**

```python
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.app_factory import build_app
from app.api.dependencies import AppState
from app.domain.models import OwnerAvailable, Tenant
from app.infrastructure.cache import TtlCache
from app.infrastructure.event_log import JsonlEventLog
from app.infrastructure.tenant_registry import TenantRegistry
from app.services.catalog_service import CatalogService
from app.services.locations_service import LocationsService
from tests.helpers.square_mock import FakeCatalogApi, FakeLocationsApi


SHARED_SECRET = "s" * 32


def _build_tenant() -> Tenant:
    return Tenant(
        slug="spicy-desi", name="Spicy Desi", twilio_number="+15555550100",
        owner_phone="+15555550199",
        owner_available=OwnerAvailable(tz="America/Chicago", weekly={"mon": ("11:00", "21:30")}),
        square_merchant_id="M1", languages=["en"], sms_confirmation_to_caller=True,
        location_overrides={}, faq="", location_notes="",
    )


@pytest.fixture
def secret() -> str:
    return SHARED_SECRET


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-Tools-Auth": SHARED_SECRET}


@pytest.fixture
def client_factory(tmp_path: Path):
    def _build(
        locations: list[dict[str, Any]] | None = None,
        catalog_items: list[dict[str, Any]] | None = None,
    ) -> tuple[TestClient, AppState]:
        tenant = _build_tenant()
        registry = TenantRegistry(
            tenants={tenant.slug: tenant},
            by_twilio_number={tenant.twilio_number: tenant.slug},
        )
        loc_svc = LocationsService(api=FakeLocationsApi(locations or []), cache=TtlCache(60))
        cat_svc = CatalogService(
            api=FakeCatalogApi(catalog_items or []), cache=TtlCache(60), specials_category_id="SPECIALS",
        )
        log = JsonlEventLog(str(tmp_path / "events.jsonl"))
        state = AppState(
            tools_shared_secret=SHARED_SECRET, tenants=registry,
            locations_service=loc_svc, catalog_service=cat_svc, event_log=log,
            square_webhook_signature_key="key",
            square_webhook_url="https://example.com/api/webhooks/square",
        )
        return TestClient(build_app(state)), state
    return _build


@pytest.fixture
def client(client_factory) -> Iterator[TestClient]:
    c, _ = client_factory()
    with c:
        yield c
```

- [ ] **Step 5: Implement `api/tests/integration/test_health.py`**

```python
from fastapi.testclient import TestClient


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
```

- [ ] **Step 6: Implement `api/tests/integration/test_auth.py`** (placeholder route exercise — needs a guarded route; we'll add `/api/locations` next, this test stays minimal for now and just verifies `/healthz` is **not** auth-gated)

```python
from fastapi.testclient import TestClient


def test_healthz_does_not_require_auth(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
```

- [ ] **Step 7: Run + commit**

```bash
pytest tests/integration/test_health.py tests/integration/test_auth.py -v
git add api/app/api/ api/tests/conftest.py api/tests/integration/__init__.py api/tests/integration/test_health.py api/tests/integration/test_auth.py
git commit -m "feat(api): FastAPI app factory + auth dependency + health route"
```

---

## Task 13: GET /api/locations

**Files:**
- Create: `api/app/api/routes/locations.py`
- Modify: `api/app/api/app_factory.py` (mount router)
- Create: `api/tests/integration/test_locations_route.py`

- [ ] **Step 1: Failing test**

```python
from fastapi.testclient import TestClient

SAMPLE = [
    {"id": "L1", "name": "Loop", "address": {"address_line_1": "111 W Madison"}, "business_hours": {"periods": []}},
]


def test_requires_auth(client_factory) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations?tenant=spicy-desi")
    assert r.status_code == 401


def test_missing_tenant_returns_400(client_factory, auth_headers) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations", headers=auth_headers)
    assert r.status_code == 400


def test_unknown_tenant_returns_404(client_factory, auth_headers) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations?tenant=nope", headers=auth_headers)
    assert r.status_code == 404


def test_returns_locations(client_factory, auth_headers) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["locations"][0]["location_id"] == "L1"
```

- [ ] **Step 2: Implement `api/app/api/routes/locations.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/locations")
async def list_locations(request: Request, tenant: str = Query(..., min_length=1)) -> dict:
    state = get_state(request)
    if tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    items = await state.locations_service.list_locations()
    return {"locations": [item.model_dump() for item in items]}
```

> Note on the 400 case: FastAPI's `Query(..., min_length=1)` returns 422 when missing. To match the test's 400, override below in `app_factory.py` validation handler, OR change the test to `422`. We choose the latter — adjust the failing test step above to expect `422` before running. (Edit test before re-running step 1 if you copied verbatim.)

Actually — to keep API behavior consistent (clients see 400 for missing required query), add a validation exception handler:

In `app_factory.py`, add:

```python
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def build_app(deps: AppState) -> FastAPI:
    app = FastAPI(title="Spicy Desi API")
    app.state.deps = deps

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(_, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": "invalid request", "details": exc.errors()}, status_code=400)

    from app.api.routes import health, locations
    app.include_router(health.router)
    app.include_router(locations.router)
    return app
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/integration/test_locations_route.py -v
git add api/app/api/routes/locations.py api/app/api/app_factory.py api/tests/integration/test_locations_route.py
git commit -m "feat(api): GET /api/locations route"
```

---

## Task 14: GET /api/locations/{id}/hours/today

**Files:**
- Create: `api/app/api/routes/hours.py`
- Modify: `api/app/api/app_factory.py`
- Create: `api/tests/integration/test_hours_route.py`

- [ ] **Step 1: Failing test**

```python
SAMPLE = [
    {
        "id": "L1", "name": "Loop", "address": {"address_line_1": "X"},
        "business_hours": {"periods": [
            {"day_of_week": "MON", "start_local_time": "11:00:00", "end_local_time": "21:30:00"},
        ]},
        "timezone": "America/Chicago",
    },
]


def test_returns_hours(client_factory, auth_headers) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations/L1/hours/today?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["open"] == "11:00"
    assert body["close"] == "21:30"
    assert body["status"] in ("open", "closed", "closing_soon")


def test_unknown_location_returns_404(client_factory, auth_headers) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations/Lnope/hours/today?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 404
```

- [ ] **Step 2: Implement `api/app/api/routes/hours.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/locations/{location_id}/hours/today")
async def hours_today(
    request: Request, location_id: str, tenant: str = Query(..., min_length=1),
) -> dict:
    state = get_state(request)
    if tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    try:
        result = await state.locations_service.get_hours_today(location_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return result.model_dump()
```

Mount in `app_factory.py`:

```python
from app.api.routes import health, locations, hours
app.include_router(hours.router)
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/integration/test_hours_route.py -v
git add api/app/api/routes/hours.py api/app/api/app_factory.py api/tests/integration/test_hours_route.py
git commit -m "feat(api): GET hours/today route"
```

---

## Task 15: GET /api/locations/{id}/address

Same shape as Task 14. Creates `api/app/api/routes/address.py`, test `test_address_route.py`.

- [ ] **Step 1: Failing test**

```python
SAMPLE = [{
    "id": "L1", "name": "Loop",
    "address": {"address_line_1": "111 W Madison", "locality": "Chicago"},
    "coordinates": {"latitude": 41.881, "longitude": -87.631},
    "business_hours": {"periods": []},
}]


def test_returns_address(client_factory, auth_headers) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations/L1/address?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "Madison" in body["formatted"]
    assert body["lat"] == 41.881


def test_unknown_returns_404(client_factory, auth_headers) -> None:
    c, _ = client_factory(locations=SAMPLE)
    r = c.get("/api/locations/Lnope/address?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 404
```

- [ ] **Step 2: Implement `api/app/api/routes/address.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/locations/{location_id}/address")
async def get_address(
    request: Request, location_id: str, tenant: str = Query(..., min_length=1),
) -> dict:
    state = get_state(request)
    if tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    try:
        result = await state.locations_service.get_address(location_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return result.model_dump()
```

Add `from app.api.routes import ... address` and `app.include_router(address.router)` in `app_factory.py`.

- [ ] **Step 3: Run + commit**

```bash
pytest tests/integration/test_address_route.py -v
git add api/app/api/routes/address.py api/app/api/app_factory.py api/tests/integration/test_address_route.py
git commit -m "feat(api): GET address route"
```

---

## Task 16: GET /api/locations/{id}/menu/search

**Files:**
- Create: `api/app/api/routes/menu.py`
- Modify: `api/app/api/app_factory.py`
- Create: `api/tests/integration/test_menu_route.py`

- [ ] **Step 1: Failing test**

```python
ITEMS = [{
    "id": "I1", "type": "ITEM",
    "item_data": {
        "name": "Chicken Tikka Masala", "description": "creamy tomato",
        "categories": [{"id": "MAINS"}],
        "variations": [{"id": "V1", "item_variation_data": {"price_money": {"amount": 1899, "currency": "USD"}}}],
    },
}]


def test_returns_match(client_factory, auth_headers) -> None:
    c, _ = client_factory(catalog_items=ITEMS)
    r = c.get("/api/locations/L1/menu/search?tenant=spicy-desi&q=tikka", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["items"][0]["name"] == "Chicken Tikka Masala"


def test_requires_q(client_factory, auth_headers) -> None:
    c, _ = client_factory(catalog_items=ITEMS)
    r = c.get("/api/locations/L1/menu/search?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 400
```

- [ ] **Step 2: Implement `api/app/api/routes/menu.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/locations/{location_id}/menu/search")
async def search_menu(
    request: Request, location_id: str,
    tenant: str = Query(..., min_length=1), q: str = Query(..., min_length=1),
) -> dict:
    _ = location_id  # currently same catalog across locations; reserved for future filtering
    state = get_state(request)
    if tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    items = await state.catalog_service.search_menu(q)
    return {"items": [i.model_dump() for i in items]}
```

Mount in `app_factory.py`. Run + commit.

---

## Task 17: GET /api/locations/{id}/specials

Same shape; route `api/app/api/routes/specials.py`, test `test_specials_route.py`.

- [ ] **Step 1: Failing test**

```python
ITEMS = [{
    "id": "I1", "type": "ITEM",
    "item_data": {
        "name": "Mango Lassi",
        "categories": [{"id": "SPECIALS"}],
        "variations": [{"id": "V1", "item_variation_data": {"price_money": {"amount": 499, "currency": "USD"}}}],
    },
}]


def test_returns_specials(client_factory, auth_headers) -> None:
    c, _ = client_factory(catalog_items=ITEMS)
    r = c.get("/api/locations/L1/specials?tenant=spicy-desi", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["items"][0]["name"] == "Mango Lassi"
```

- [ ] **Step 2: Implement**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/locations/{location_id}/specials")
async def list_specials(
    request: Request, location_id: str, tenant: str = Query(..., min_length=1),
) -> dict:
    _ = location_id
    state = get_state(request)
    if tenant not in state.tenants.tenants:
        raise HTTPException(404, "tenant not found")
    items = await state.catalog_service.get_specials()
    return {"items": [i.model_dump() for i in items]}
```

Mount + commit.

---

## Task 18: POST /api/messages (skeleton — logs to JSONL)

**Files:**
- Create: `api/app/api/routes/messages.py`
- Modify: `api/app/api/app_factory.py`
- Create: `api/tests/integration/test_messages_route.py`

- [ ] **Step 1: Failing test**

```python
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("body, expected_status", [
    ({"call_sid": "CA1", "callback_number": "+1555", "reason": "catering"}, 202),
])
def test_messages_records_event(client_factory, auth_headers, tmp_path: Path, body, expected_status) -> None:
    c, state = client_factory()
    r = c.post("/api/messages", headers=auth_headers, json=body)
    assert r.status_code == expected_status
    log_path = Path(state.event_log._path)  # noqa: SLF001
    line = log_path.read_text().splitlines()[0]
    rec = json.loads(line)
    assert rec["call_sid"] == "CA1"
    assert rec["kind"] == "message_taken"


def test_messages_requires_callback_number(client_factory, auth_headers) -> None:
    c, _ = client_factory()
    r = c.post("/api/messages", headers=auth_headers, json={"call_sid": "CA1", "reason": "x"})
    assert r.status_code == 400
```

- [ ] **Step 2: Implement `api/app/api/routes/messages.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_state, require_tools_auth
from app.domain.models import EventRecord, MessageRequest

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.post("/messages", status_code=202)
async def take_message(request: Request, body: MessageRequest) -> dict:
    state = get_state(request)
    await state.event_log.append(EventRecord(
        call_sid=body.call_sid, kind="message_taken", payload=body.model_dump(),
    ))
    return {"ok": True, "sms_sent": False}  # SMS wired in Plan 2
```

Mount + commit.

---

## Task 19: POST /api/transfers

**Files:**
- Create: `api/app/api/routes/transfers.py`
- Modify: `api/app/api/app_factory.py`
- Create: `api/tests/integration/test_transfers_route.py`

- [ ] **Step 1: Failing test**

```python
def test_returns_take_message_outside_hours(client_factory, auth_headers) -> None:
    c, _ = client_factory()
    # Sunday — owner_available config has only "mon"
    r = c.post(
        "/api/transfers?now=2026-05-03T09:00:00Z",
        headers=auth_headers,
        json={"call_sid": "CA1", "reason": "owner please"},
    )
    assert r.status_code == 200
    assert r.json()["action"] == "take_message"


def test_returns_transfer_in_hours(client_factory, auth_headers) -> None:
    c, _ = client_factory()
    # Monday 14:00 Chicago = 20:00 UTC
    r = c.post(
        "/api/transfers?now=2026-01-05T20:00:00Z",
        headers=auth_headers,
        json={"call_sid": "CA1", "reason": "owner please"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "transfer"
    assert body["target"] == "+15555550199"
```

- [ ] **Step 2: Implement `api/app/api/routes/transfers.py`**

```python
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_state, require_tools_auth
from app.domain.models import EventRecord, TransferRequest
from app.services.transfer_decision_service import decide_transfer

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.post("/transfers")
async def request_transfer(
    request: Request, body: TransferRequest, now: str | None = Query(None),
) -> dict:
    state = get_state(request)
    tenant = state.tenants.tenants.get("spicy-desi")
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00")) if now else None
    decision = decide_transfer(tenant, now=now_dt)
    await state.event_log.append(EventRecord(
        call_sid=body.call_sid, kind="transfer_decided",
        payload={"decision": decision.model_dump(), "reason": body.reason},
    ))
    return decision.model_dump()
```

Mount + commit.

---

## Task 20: POST /api/calls/{sid}/event

Generic event-append endpoint Pipecat will use to log call lifecycle + transcript chunks.

**Files:**
- Create: `api/app/api/routes/events.py`
- Modify: `api/app/api/app_factory.py`
- Create: `api/tests/integration/test_events_route.py`

- [ ] **Step 1: Failing test**

```python
import json
from pathlib import Path


def test_appends_event(client_factory, auth_headers) -> None:
    c, state = client_factory()
    r = c.post(
        "/api/calls/CA1/event",
        headers=auth_headers,
        json={"kind": "transcript_chunk", "payload": {"role": "user", "text": "hello"}},
    )
    assert r.status_code == 202
    line = Path(state.event_log._path).read_text().splitlines()[0]  # noqa: SLF001
    rec = json.loads(line)
    assert rec["call_sid"] == "CA1"
    assert rec["kind"] == "transcript_chunk"
```

- [ ] **Step 2: Implement `api/app/api/routes/events.py`**

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.dependencies import get_state, require_tools_auth
from app.domain.models import EventRecord

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


class EventBody(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/calls/{call_sid}/event", status_code=202)
async def append_call_event(request: Request, call_sid: str, body: EventBody) -> dict:
    state = get_state(request)
    await state.event_log.append(EventRecord(
        call_sid=call_sid, kind=body.kind, payload=body.payload,
    ))
    return {"ok": True}
```

Mount + commit.

---

## Task 21: POST /api/webhooks/square

**Files:**
- Create: `api/app/api/routes/webhooks_square.py`
- Modify: `api/app/api/app_factory.py`
- Create: `api/tests/integration/test_square_webhook.py`

- [ ] **Step 1: Failing test**

```python
import base64
import hashlib
import hmac
import json


def test_rejects_bad_signature(client_factory) -> None:
    c, _ = client_factory()
    r = c.post(
        "/api/webhooks/square",
        headers={"X-Square-Hmacsha256-Signature": "bad", "Content-Type": "application/json"},
        content=json.dumps({"type": "catalog.version.updated"}),
    )
    assert r.status_code == 401


def test_invalidates_on_valid_signature(client_factory) -> None:
    c, state = client_factory()
    body = json.dumps({"type": "catalog.version.updated"})
    sig = base64.b64encode(
        hmac.new(state.square_webhook_signature_key.encode(),
                 (state.square_webhook_url + body).encode(),
                 hashlib.sha256).digest()
    ).decode()
    r = c.post(
        "/api/webhooks/square",
        headers={"X-Square-Hmacsha256-Signature": sig, "Content-Type": "application/json"},
        content=body,
    )
    assert r.status_code == 200
```

- [ ] **Step 2: Implement `api/app/api/routes/webhooks_square.py`**

```python
from __future__ import annotations

import base64
import hashlib
import hmac

from fastapi import APIRouter, Header, HTTPException, Request

from app.api.dependencies import get_state

router = APIRouter(prefix="/api/webhooks")


@router.post("/square")
async def square_webhook(
    request: Request, x_square_hmacsha256_signature: str | None = Header(default=None),
) -> dict:
    state = get_state(request)
    body = await request.body()
    expected = base64.b64encode(
        hmac.new(
            state.square_webhook_signature_key.encode(),
            (state.square_webhook_url + body.decode()).encode(),
            hashlib.sha256,
        ).digest()
    ).decode()
    provided = x_square_hmacsha256_signature or ""
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "invalid signature")
    state.catalog_service.invalidate()
    state.locations_service._cache.clear()  # type: ignore[attr-defined]  # noqa: SLF001
    return {"ok": True}
```

Mount + commit.

---

## Task 22: Process entrypoint + local smoke test

**Files:**
- Create: `api/app/main.py`

- [ ] **Step 1: Implement `api/app/main.py`**

```python
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv  # type: ignore[import-untyped]

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.api.app_factory import build_app  # noqa: E402
from app.api.dependencies import AppState  # noqa: E402
from app.infrastructure.cache import TtlCache  # noqa: E402
from app.infrastructure.config import AppSettings  # noqa: E402
from app.infrastructure.event_log import JsonlEventLog  # noqa: E402
from app.infrastructure.logger import configure_logging, get_logger  # noqa: E402
from app.infrastructure.square_client import (  # noqa: E402
    SquareCatalogAdapter, SquareLocationsAdapter, make_square_client,
)
from app.infrastructure.tenant_registry import load_tenants  # noqa: E402
from app.services.catalog_service import CatalogService  # noqa: E402
from app.services.locations_service import LocationsService  # noqa: E402


def _build() -> "FastAPI":  # type: ignore[name-defined]
    settings = AppSettings()
    configure_logging(settings.log_level)
    log = get_logger("startup")
    log.info("loading tenants", configs_dir=settings.configs_dir)

    sq_client = make_square_client(
        access_token=settings.square_access_token, environment=settings.square_environment,
    )
    locations_service = LocationsService(
        api=SquareLocationsAdapter(sq_client),
        cache=TtlCache(ttl_seconds=60 * 60),
    )
    catalog_service = CatalogService(
        api=SquareCatalogAdapter(sq_client),
        cache=TtlCache(ttl_seconds=5 * 60),
        specials_category_id="SPECIALS",
    )
    state = AppState(
        tools_shared_secret=settings.tools_shared_secret,
        tenants=load_tenants(settings.configs_dir),
        locations_service=locations_service,
        catalog_service=catalog_service,
        event_log=JsonlEventLog(settings.event_log_path),
        square_webhook_signature_key=settings.square_webhook_signature_key,
        square_webhook_url=settings.square_webhook_url,
    )
    return build_app(state)


app = _build()
```

Add `python-dotenv` to deps (pyproject.toml dependencies).

- [ ] **Step 2: Smoke test**

```bash
cd api
source .venv/bin/activate
TOOLS_SHARED_SECRET=$(python -c 'print("x"*32)') \
SQUARE_ACCESS_TOKEN=fake \
SQUARE_ENVIRONMENT=sandbox \
SQUARE_WEBHOOK_SIGNATURE_KEY=fake \
SQUARE_WEBHOOK_URL=https://example.com \
CONFIGS_DIR=../configs \
EVENT_LOG_PATH=./data/events.jsonl \
PORT=18080 \
uvicorn app.main:app --port 18080 &
SERVER_PID=$!
sleep 2
curl -fsS http://localhost:18080/healthz
echo
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:18080/api/locations?tenant=spicy-desi
kill $SERVER_PID 2>/dev/null || true
```

Expected: `{"ok":true}` and `401`.

- [ ] **Step 3: Commit**

```bash
git add api/app/main.py api/pyproject.toml
git commit -m "feat(api): main.py wires real adapters + boots FastAPI"
```

---

## Task 23: Final validation pass + README update

- [ ] **Step 1: Full test suite**

```bash
cd api && source .venv/bin/activate && pytest -v
```

Expected: all green.

- [ ] **Step 2: Lint + typecheck**

```bash
ruff check .
ruff format --check .
mypy app
```

Expected: clean.

- [ ] **Step 3: Update root README with API surface**

Append to `/Users/milindp/Coding/Repos/spicydesichciago-agent/README.md`:

```markdown
## API endpoints (Plan 1)

All `/api/*` endpoints require `X-Tools-Auth: $TOOLS_SHARED_SECRET`. Tenant is selected via `?tenant=<slug>`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness |
| GET | `/api/locations` | List Square locations |
| GET | `/api/locations/{id}/hours/today` | Today's hours + status |
| GET | `/api/locations/{id}/address` | Formatted address + coords |
| GET | `/api/locations/{id}/menu/search?q=` | Menu search via Square Catalog |
| GET | `/api/locations/{id}/specials` | Items in the SPECIALS category |
| POST | `/api/messages` | Record a take-message; appends to event log (Twilio SMS in Plan 2) |
| POST | `/api/transfers` | Decide transfer-vs-take-message based on owner-available hours (Twilio REST in Plan 2) |
| POST | `/api/calls/{sid}/event` | Generic call-event log append |
| POST | `/api/webhooks/square` | Square webhook (HMAC-verified) — invalidates cache |
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: list Plan 1 API surface"
```

---

## What's deferred to Plan 2

- Real Twilio SMS in `/api/messages` (today: just logs)
- Real Twilio REST live-call redirect in `/api/transfers` (today: just decides)
- Pipecat agent calling these endpoints
- Hindi/Telugu Cartesia voice tuning

## What's deferred to Plan 3

- Oracle Cloud deployment (systemd, Caddy, runbook) — designed in Plan 1 but applied in Plan 3
- R2 backups of `data/events.jsonl`
- End-to-end multilingual call testing
- Soft-launch monitoring
