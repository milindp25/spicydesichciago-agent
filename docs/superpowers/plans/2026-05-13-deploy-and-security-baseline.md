# Deploy + Security Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dockerize the `agent` and `api` services, deploy both to Fly.io behind custom domains (`agent.spicydesichicago.com`, `api.spicydesichicago.com`), wire Twilio signature validation on all agent webhook routes, and validate one real inbound call end-to-end.

**Architecture:** Two separate Fly apps (`spicy-desi-agent` public WSS + HTTPS, `spicy-desi-api` public HTTPS). Agent → API uses Fly's internal `.flycast` DNS with a shared `INTERNAL_API_TOKEN` (defense-in-depth). All Twilio inbound webhooks validated via `X-Twilio-Signature` HMAC. CORS pinned to `https://spicydesichicago.com`. Docker-first so the same images can later target Cloud Run with one env-var swap.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, Pipecat 1.1, Twilio SDK, Docker, Fly.io, Let's Encrypt (via Fly).

**Branch:** `feature/fly-deploy-and-security` (already created from `main`).

**Out of scope for this plan:** Firebase RTDB persistence (separate plan), Firebase Auth ID tokens for dashboard (separate plan), rate limiting middleware (separate plan), Firebase service account wiring (separate plan).

---

## Pre-flight context

- `agent/.venv` exists (Python 3.12). `api/` has **no** venv yet — Task 1.2 creates it.
- `docker` and `flyctl` are **not** installed on this Mac — Task 0 installs them.
- Existing agent tests: 45 passing. API tests need verification post-venv-setup.
- `agent/app/config.py` already exposes `twilio_auth_token`; the value just isn't used yet.
- `api/app/api/routes/webhooks_square.py` **already validates** `X-Square-HmacSha256-Signature` — no change needed there.
- `agent/app/server.py` `/twilio/inbound`, `/twilio/dial-owner`, `/twilio/dial-owner-fallback` are the three routes that need signature validation.

---

## Phase 0 — Prerequisites

### Task 0.1: Install Docker and flyctl

**Files:** None (local machine setup).

- [ ] **Step 1: Install OrbStack (Docker runtime — lighter than Docker Desktop, free for personal use)**

```bash
brew install --cask orbstack
open -a OrbStack
```

Wait for OrbStack to finish initializing (menu bar icon appears).

- [ ] **Step 2: Verify Docker works**

```bash
docker --version
docker run --rm hello-world
```

Expected: prints "Hello from Docker!".

- [ ] **Step 3: Install flyctl**

```bash
brew install flyctl
```

- [ ] **Step 4: Verify flyctl**

```bash
flyctl version
```

Expected: prints flyctl version (>= 0.3.0).

- [ ] **Step 5: Authenticate to Fly.io**

```bash
flyctl auth signup    # or: flyctl auth login
```

Follow the browser flow. Verify with:

```bash
flyctl auth whoami
```

Expected: prints your Fly.io email.

- [ ] **Step 6: No commit (local-machine tooling, nothing to commit).**

---

### Task 0.2: Confirm we're on the right branch

**Files:** None.

- [ ] **Step 1: Verify branch**

```bash
git branch --show-current
```

Expected: `feature/fly-deploy-and-security`

- [ ] **Step 2: Verify we're up to date with main**

```bash
git log --oneline main..HEAD
```

Expected: empty (no commits yet on this branch).

---

## Phase 1 — Test baseline

### Task 1.1: Run agent test suite baseline

**Files:** None (verification only).

- [ ] **Step 1: Run agent tests**

```bash
(cd agent && .venv/bin/pytest tests/ -v 2>&1 | tail -30)
```

Expected: `45 passed` (this is the current baseline). If anything fails, STOP and fix before continuing — do not introduce changes on top of broken tests.

---

### Task 1.2: Create API venv and run API tests

**Files:** None (creates `api/.venv` which is gitignored).

- [ ] **Step 1: Create venv**

```bash
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv api/.venv
```

- [ ] **Step 2: Install API deps**

```bash
api/.venv/bin/pip install --upgrade pip
api/.venv/bin/pip install -e "api/.[dev]"
```

Expected: installs FastAPI, squareup, twilio, pytest, mypy. Should complete without errors.

- [ ] **Step 3: Run API tests**

```bash
(cd api && .venv/bin/pytest tests/ -v 2>&1 | tail -40)
```

Expected: all tests pass. Record the count. If anything fails, STOP — we need green baseline before changes.

- [ ] **Step 4: Add `.venv/` to root `.gitignore` if not present**

Check first:

```bash
grep -E "^\.?venv|^.*\.venv" .gitignore 2>/dev/null
```

If empty, append:

```bash
cat >> .gitignore <<'EOF'

# Python venvs
.venv/
*/.venv/
EOF
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git diff --cached --quiet || git commit -m "chore: ensure .venv is gitignored at all levels"
```

(The `git diff --cached --quiet || ...` pattern skips the commit if there's nothing to add — `.venv` may already be ignored.)

---

## Phase 2 — Twilio signature validation (TDD)

This phase ships **before** Dockerization so we can prove correctness via unit + integration tests locally, then carry it into the deploy.

### Task 2.1: Add `twilio` dependency to agent (verify already present)

**Files:** `agent/pyproject.toml`

- [ ] **Step 1: Verify `twilio` is already in agent deps**

```bash
grep "twilio" agent/pyproject.toml
```

Expected: `twilio>=9.3.0` line present. If not, add it under `dependencies`. The `twilio` package ships `twilio.request_validator.RequestValidator` which we need.

- [ ] **Step 2: If you added the line, reinstall**

```bash
(cd agent && .venv/bin/pip install -e ".[dev]")
```

If unchanged, skip.

---

### Task 2.2: Write failing tests for `TwilioSignatureVerifier`

**Files:**
- Create: `agent/app/security/__init__.py` (empty package marker — create empty)
- Test: `agent/tests/unit/test_twilio_signature.py`

- [ ] **Step 1: Create empty package init**

```bash
mkdir -p agent/app/security
touch agent/app/security/__init__.py
```

- [ ] **Step 2: Write the test file**

Create `agent/tests/unit/test_twilio_signature.py`:

```python
"""Tests for TwilioSignatureVerifier."""
from __future__ import annotations

import pytest
from twilio.request_validator import RequestValidator

from app.security.twilio_signature import TwilioSignatureVerifier


AUTH_TOKEN = "test-auth-token-32-bytes-long-xx"
URL = "https://agent.spicydesichicago.com/twilio/inbound"
FORM = {"From": "+15551234567", "CallSid": "CA123"}


def _make_signature(token: str, url: str, form: dict[str, str]) -> str:
    return RequestValidator(token).compute_signature(url, form)


def test_accepts_valid_signature() -> None:
    verifier = TwilioSignatureVerifier(auth_token=AUTH_TOKEN)
    sig = _make_signature(AUTH_TOKEN, URL, FORM)
    assert verifier.verify(url=URL, form=FORM, signature=sig) is True


def test_rejects_missing_signature() -> None:
    verifier = TwilioSignatureVerifier(auth_token=AUTH_TOKEN)
    assert verifier.verify(url=URL, form=FORM, signature="") is False
    assert verifier.verify(url=URL, form=FORM, signature=None) is False


def test_rejects_tampered_signature() -> None:
    verifier = TwilioSignatureVerifier(auth_token=AUTH_TOKEN)
    sig = _make_signature(AUTH_TOKEN, URL, FORM)
    tampered = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    assert verifier.verify(url=URL, form=FORM, signature=tampered) is False


def test_rejects_signature_with_wrong_token() -> None:
    verifier = TwilioSignatureVerifier(auth_token=AUTH_TOKEN)
    sig = _make_signature("different-token-32-bytes-long-yy", URL, FORM)
    assert verifier.verify(url=URL, form=FORM, signature=sig) is False


def test_rejects_signature_with_modified_form() -> None:
    verifier = TwilioSignatureVerifier(auth_token=AUTH_TOKEN)
    sig = _make_signature(AUTH_TOKEN, URL, FORM)
    modified = {**FORM, "From": "+15559999999"}
    assert verifier.verify(url=URL, form=modified, signature=sig) is False


def test_empty_auth_token_disables_verification() -> None:
    """If TWILIO_AUTH_TOKEN is unset (empty), verifier is in dev mode and accepts all."""
    verifier = TwilioSignatureVerifier(auth_token="")
    assert verifier.verify(url=URL, form=FORM, signature="anything") is True
    assert verifier.is_enabled() is False


def test_enabled_when_token_present() -> None:
    verifier = TwilioSignatureVerifier(auth_token=AUTH_TOKEN)
    assert verifier.is_enabled() is True
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_twilio_signature.py -v 2>&1 | tail -20)
```

Expected: ImportError or "ModuleNotFoundError: No module named 'app.security.twilio_signature'" — confirming we haven't implemented yet.

---

### Task 2.3: Implement `TwilioSignatureVerifier`

**Files:**
- Create: `agent/app/security/twilio_signature.py`

- [ ] **Step 1: Implement**

Create `agent/app/security/twilio_signature.py`:

```python
"""Validate inbound Twilio webhooks via X-Twilio-Signature."""
from __future__ import annotations

from twilio.request_validator import RequestValidator


class TwilioSignatureVerifier:
    """
    Wraps Twilio's RequestValidator with a dev-mode bypass.

    When auth_token is empty (typical in local development without Twilio
    credentials), verification is disabled and verify() returns True. In
    production the token must be set or all webhooks are rejected.
    """

    def __init__(self, auth_token: str) -> None:
        self._token = auth_token
        self._validator = RequestValidator(auth_token) if auth_token else None

    def is_enabled(self) -> bool:
        return self._validator is not None

    def verify(
        self,
        *,
        url: str,
        form: dict[str, str],
        signature: str | None,
    ) -> bool:
        if self._validator is None:
            return True
        if not signature:
            return False
        return self._validator.validate(url, form, signature)
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
(cd agent && .venv/bin/pytest tests/unit/test_twilio_signature.py -v 2>&1 | tail -20)
```

Expected: all 7 tests pass.

- [ ] **Step 3: Run full agent test suite to confirm no regression**

```bash
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -10)
```

Expected: `52 passed` (45 original + 7 new).

- [ ] **Step 4: Commit**

```bash
git add agent/app/security/ agent/tests/unit/test_twilio_signature.py
git commit -m "feat(agent): add TwilioSignatureVerifier with dev-mode bypass

Wraps twilio SDK's RequestValidator. When TWILIO_AUTH_TOKEN is empty
(local dev), verification is disabled. In production an unset token
means all webhooks are rejected, which is the safe default.

7 unit tests cover positive/negative/tampered/wrong-token/modified-form
paths plus the dev-mode bypass."
```

---

### Task 2.4: Write failing integration test for `/twilio/inbound` signature enforcement

**Files:**
- Test: `agent/tests/integration/test_twilio_inbound_signature.py`

- [ ] **Step 1: Read existing integration tests for style**

```bash
cat agent/tests/integration/test_server_routes.py
```

Note how `build_app(settings)` is called and how `TestClient` is used.

- [ ] **Step 2: Write the failing test**

Create `agent/tests/integration/test_twilio_inbound_signature.py`:

```python
"""Integration tests: /twilio/inbound must reject unsigned requests in production mode."""
from __future__ import annotations

from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.config import AgentSettings
from app.server import build_app


def _settings_with_token(token: str) -> AgentSettings:
    """Build settings with required fields populated for tests."""
    return AgentSettings(
        TOOLS_API_BASE="http://test-api",
        TOOLS_SHARED_SECRET="x" * 32,
        GROQ_API_KEY="test",
        DEEPGRAM_API_KEY="test",
        CARTESIA_API_KEY="test",
        CARTESIA_VOICE_ID="test-voice",
        TWILIO_AUTH_TOKEN=token,
    )


def test_inbound_rejects_unsigned_when_token_set() -> None:
    app = build_app(_settings_with_token("real-auth-token-32-bytes-long-xx"))
    client = TestClient(app)
    resp = client.post("/twilio/inbound", data={"From": "+15551234567"})
    assert resp.status_code == 403


def test_inbound_accepts_valid_signature() -> None:
    token = "real-auth-token-32-bytes-long-xx"
    app = build_app(_settings_with_token(token))
    client = TestClient(app)

    form = {"From": "+15551234567"}
    url = "http://testserver/twilio/inbound"
    sig = RequestValidator(token).compute_signature(url, form)

    resp = client.post("/twilio/inbound", data=form, headers={"X-Twilio-Signature": sig})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert "<Stream" in resp.text


def test_inbound_accepts_anything_in_dev_mode() -> None:
    """Empty token = dev mode, anything goes."""
    app = build_app(_settings_with_token(""))
    client = TestClient(app)
    resp = client.post("/twilio/inbound", data={"From": "+15551234567"})
    assert resp.status_code == 200
    assert "<Stream" in resp.text
```

- [ ] **Step 3: Run to verify it fails**

```bash
(cd agent && .venv/bin/pytest tests/integration/test_twilio_inbound_signature.py -v 2>&1 | tail -20)
```

Expected: `test_inbound_rejects_unsigned_when_token_set` FAILS (currently returns 200 because no validation is wired). Possibly `test_inbound_accepts_valid_signature` also fails. `test_inbound_accepts_anything_in_dev_mode` should pass since no validation is present.

---

### Task 2.5: Wire `TwilioSignatureVerifier` into `/twilio/inbound`

**Files:**
- Modify: `agent/app/server.py`

- [ ] **Step 1: Edit `agent/app/server.py` — update imports**

Find:

```python
from fastapi import FastAPI, Form, Query, Request, WebSocket
from fastapi.responses import PlainTextResponse

from app.bot import run_bot
from app.config import AgentSettings
```

Replace with:

```python
from fastapi import FastAPI, Form, HTTPException, Query, Request, WebSocket
from fastapi.responses import PlainTextResponse

from app.bot import run_bot
from app.config import AgentSettings
from app.security.twilio_signature import TwilioSignatureVerifier
```

- [ ] **Step 2: Add verifier creation and helper inside `build_app`**

Find:

```python
def build_app(settings: AgentSettings) -> FastAPI:
    app = FastAPI(title="Spicy Desi Agent")

    @app.get("/healthz")
```

Replace with:

```python
def build_app(settings: AgentSettings) -> FastAPI:
    app = FastAPI(title="Spicy Desi Agent")
    verifier = TwilioSignatureVerifier(auth_token=settings.twilio_auth_token)

    def _full_url(request: Request) -> str:
        # Behind Fly's proxy, Uvicorn must run with --proxy-headers so
        # request.url.scheme reflects X-Forwarded-Proto. We reconstruct
        # the URL from scheme + host header + path to match what Twilio
        # signed.
        scheme = request.url.scheme
        host = request.headers.get("host", "")
        return f"{scheme}://{host}{request.url.path}"

    async def _verify_twilio(request: Request) -> dict[str, str]:
        form = await request.form()
        form_dict = {k: str(v) for k, v in form.items()}
        sig = request.headers.get("X-Twilio-Signature")
        if not verifier.verify(url=_full_url(request), form=form_dict, signature=sig):
            raise HTTPException(status_code=403, detail="invalid twilio signature")
        return form_dict

    @app.get("/healthz")
```

- [ ] **Step 3: Update `/twilio/inbound` to use the verifier**

Find:

```python
    @app.post("/twilio/inbound")
    async def twilio_inbound(
        request: Request,
        from_phone: str | None = Form(None, alias="From"),
    ) -> PlainTextResponse:
        host = request.headers.get("host", "")
```

Replace with:

```python
    @app.post("/twilio/inbound")
    async def twilio_inbound(request: Request) -> PlainTextResponse:
        form_dict = await _verify_twilio(request)
        from_phone = form_dict.get("From")
        host = request.headers.get("host", "")
```

(The `Form` import remains in use by other code paths; keep it.)

- [ ] **Step 4: Run integration tests**

```bash
(cd agent && .venv/bin/pytest tests/integration/test_twilio_inbound_signature.py -v 2>&1 | tail -20)
```

Expected: all 3 tests pass.

- [ ] **Step 5: Run the FULL agent test suite to confirm we didn't break existing routes**

```bash
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -10)
```

Expected: `55 passed` (52 + 3 new integration tests). If anything in `test_server_routes.py` fails because it was hitting `/twilio/inbound` without a signature, fix those tests by either: (a) setting `TWILIO_AUTH_TOKEN=""` in test settings to enable dev-mode, or (b) signing the test request. Inspect the failure and decide based on intent.

- [ ] **Step 6: Commit**

```bash
git add agent/app/server.py agent/tests/integration/test_twilio_inbound_signature.py
git commit -m "feat(agent): enforce X-Twilio-Signature on /twilio/inbound

Wires TwilioSignatureVerifier into the inbound webhook. Returns 403 on
missing or invalid signature when TWILIO_AUTH_TOKEN is set; falls back
to dev-mode (accept all) when token is empty for local development.

3 integration tests cover production reject, production accept, dev mode."
```

---

### Task 2.6: Extend signature validation to `/twilio/dial-owner` and `/twilio/dial-owner-fallback`

**Files:**
- Modify: `agent/app/server.py`
- Test: `agent/tests/integration/test_twilio_inbound_signature.py` (extend)

- [ ] **Step 1: Add failing tests for the other two routes**

Append to `agent/tests/integration/test_twilio_inbound_signature.py`:

```python
def test_dial_owner_rejects_unsigned() -> None:
    app = build_app(_settings_with_token("real-auth-token-32-bytes-long-xx"))
    client = TestClient(app)
    resp = client.post("/twilio/dial-owner?to=%2B15551112222")
    assert resp.status_code == 403


def test_dial_owner_accepts_valid_signature() -> None:
    token = "real-auth-token-32-bytes-long-xx"
    app = build_app(_settings_with_token(token))
    client = TestClient(app)
    url = "http://testserver/twilio/dial-owner?to=%2B15551112222"
    sig = RequestValidator(token).compute_signature(url, {})
    resp = client.post(
        "/twilio/dial-owner?to=%2B15551112222",
        headers={"X-Twilio-Signature": sig},
    )
    assert resp.status_code == 200
    assert "<Dial" in resp.text


def test_dial_owner_fallback_rejects_unsigned() -> None:
    app = build_app(_settings_with_token("real-auth-token-32-bytes-long-xx"))
    client = TestClient(app)
    resp = client.post("/twilio/dial-owner-fallback", data={"DialCallStatus": "completed"})
    assert resp.status_code == 403


def test_dial_owner_fallback_accepts_valid_signature() -> None:
    token = "real-auth-token-32-bytes-long-xx"
    app = build_app(_settings_with_token(token))
    client = TestClient(app)
    form = {"DialCallStatus": "completed"}
    url = "http://testserver/twilio/dial-owner-fallback"
    sig = RequestValidator(token).compute_signature(url, form)
    resp = client.post(
        "/twilio/dial-owner-fallback",
        data=form,
        headers={"X-Twilio-Signature": sig},
    )
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify failures**

```bash
(cd agent && .venv/bin/pytest tests/integration/test_twilio_inbound_signature.py -v 2>&1 | tail -20)
```

Expected: the 4 new tests fail because validation isn't wired on those routes yet.

- [ ] **Step 3: Wire validation into `/twilio/dial-owner`**

In `agent/app/server.py`, find:

```python
    @app.post("/twilio/dial-owner")
    async def dial_owner(to: str = Query(...)) -> PlainTextResponse:
```

Replace with:

```python
    @app.post("/twilio/dial-owner")
    async def dial_owner(request: Request, to: str = Query(...)) -> PlainTextResponse:
        await _verify_twilio(request)
```

(Body of function below stays the same.)

- [ ] **Step 4: Wire validation into `/twilio/dial-owner-fallback`**

Find:

```python
    @app.post("/twilio/dial-owner-fallback")
    async def dial_owner_fallback(
        request: Request,
        DialCallStatus: str | None = Form(None),  # noqa: N803
    ) -> PlainTextResponse:
        host = request.headers.get("host", "")
```

Replace with:

```python
    @app.post("/twilio/dial-owner-fallback")
    async def dial_owner_fallback(request: Request) -> PlainTextResponse:
        form_dict = await _verify_twilio(request)
        DialCallStatus = form_dict.get("DialCallStatus")  # noqa: N806
        host = request.headers.get("host", "")
```

- [ ] **Step 5: Run the 4 new tests**

```bash
(cd agent && .venv/bin/pytest tests/integration/test_twilio_inbound_signature.py -v 2>&1 | tail -20)
```

Expected: all tests in that file pass.

- [ ] **Step 6: Run full suite**

```bash
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -10)
```

Expected: all 59 tests pass (55 + 4 new). Fix any regressions in `test_server_routes.py` if they exist.

- [ ] **Step 7: Commit**

```bash
git add agent/app/server.py agent/tests/integration/test_twilio_inbound_signature.py
git commit -m "feat(agent): enforce X-Twilio-Signature on dial-owner routes"
```

---

## Phase 3 — Dockerize

### Task 3.1: Add `/healthz` to API (verify it exists)

**Files:** None expected (just verification).

- [ ] **Step 1: Verify endpoint exists**

```bash
grep -r "/healthz\|/health" api/app/api/routes/health.py
```

Expected: `@router.get("/healthz")` line present. If missing, add it per the existing pattern in `api/app/api/routes/health.py`. (Already verified during planning — should be present.)

- [ ] **Step 2: Test it boots locally**

```bash
(cd api && APP_ENV=test \
  TOOLS_SHARED_SECRET="$(printf 'x%.0s' {1..32})" \
  SQUARE_ACCESS_TOKEN="test" SQUARE_ENVIRONMENT="sandbox" \
  SQUARE_WEBHOOK_SIGNATURE_KEY="test" \
  CONFIGS_DIR="../configs" \
  .venv/bin/uvicorn app.main:app --port 18080 &)
sleep 3
curl -fsS http://localhost:18080/healthz
kill %1 2>/dev/null
```

Expected: prints `{"ok":true}`.

---

### Task 3.2: Create agent Dockerfile

**Files:**
- Create: `agent/Dockerfile`
- Create: `agent/.dockerignore`

- [ ] **Step 1: Write `.dockerignore`**

Create `agent/.dockerignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
tests/
*.md
.env*
```

- [ ] **Step 2: Write `Dockerfile`**

Create `agent/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
RUN pip install --prefix=/install .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/app"

WORKDIR /app
COPY --from=builder /install /install
COPY app ./app

# Pipecat needs libgomp1 at runtime for some audio ops (silero, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
 && rm -rf /var/lib/apt/lists/*

EXPOSE 8090

# --proxy-headers + --forwarded-allow-ips so request.url.scheme reflects
# X-Forwarded-Proto from Fly's edge. Critical for Twilio signature
# validation: the URL Twilio signed is https://..., not http://...
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
```

- [ ] **Step 3: Build the image locally**

```bash
docker build -t spicy-desi-agent:local agent/
```

Expected: successful build. If `pipecat-ai[silero,...]` fails to install, you may need to add more apt deps to builder stage (e.g. `cmake`). Adjust as needed.

- [ ] **Step 4: Quick boot test (without real secrets, just check it starts and fails-fast on missing env)**

```bash
docker run --rm spicy-desi-agent:local 2>&1 | head -20
```

Expected: the container starts and immediately fails because required env vars (e.g. `TOOLS_API_BASE`, `GROQ_API_KEY`) are missing. That's correct — pydantic-settings raises ValidationError. This proves the image is structurally sound.

- [ ] **Step 5: Boot with minimal valid env to confirm `/healthz` responds**

```bash
docker run --rm -d --name spicy-agent-test -p 18090:8090 \
  -e TOOLS_API_BASE="http://test" \
  -e TOOLS_SHARED_SECRET="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -e GROQ_API_KEY="test" \
  -e DEEPGRAM_API_KEY="test" \
  -e CARTESIA_API_KEY="test" \
  -e CARTESIA_VOICE_ID="test-voice" \
  -e TWILIO_AUTH_TOKEN="" \
  spicy-desi-agent:local
sleep 3
curl -fsS http://localhost:18090/healthz
docker rm -f spicy-agent-test
```

Expected: prints `{"ok":true}` then removes the container.

- [ ] **Step 6: Commit**

```bash
git add agent/Dockerfile agent/.dockerignore
git commit -m "feat(agent): add Dockerfile (python:3.12-slim, multi-stage)

Multi-stage build, runtime layer has only libgomp1 + installed package.
Runs uvicorn with --proxy-headers --forwarded-allow-ips=* so Twilio
signature validation sees the original https:// URL behind Fly's proxy."
```

---

### Task 3.3: Create API Dockerfile

**Files:**
- Create: `api/Dockerfile`
- Create: `api/.dockerignore`

- [ ] **Step 1: Write `.dockerignore`**

Create `api/.dockerignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/
tests/
*.md
.env*
data/
```

Note: `data/` is excluded — production data lives on a Fly volume, not baked into the image. Local dev data stays out.

- [ ] **Step 2: Write `Dockerfile`**

Create `api/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
RUN pip install --prefix=/install .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/install/bin:$PATH" PYTHONPATH="/app"

WORKDIR /app
COPY --from=builder /install /install
COPY app ./app

# Configs are baked into the image so we don't need a volume just for them.
# (Per-tenant runtime overrides come from env vars / Firebase later.)
COPY ../configs ./configs

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
```

Wait — Docker can't use `..` in COPY. The build context is `api/`. We need the configs available. Two options: (a) build with context=repo root, or (b) symlink configs into api/ at build time. **Option (a) is cleaner.** Update the file:

Replace the configs COPY line and adjust:

```dockerfile
# Build with: docker build -f api/Dockerfile -t spicy-desi-api:local .
# (Context = repo root so we can COPY configs/)
```

And restructure to use repo-root context. Rewrite the file:

```dockerfile
# syntax=docker/dockerfile:1.7
# Build from repo root: docker build -f api/Dockerfile -t spicy-desi-api:local .
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY api/pyproject.toml ./
COPY api/app ./app
RUN pip install --prefix=/install .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/install/bin:$PATH" PYTHONPATH="/app" \
    CONFIGS_DIR=/app/configs

WORKDIR /app
COPY --from=builder /install /install
COPY api/app ./app
COPY configs ./configs

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
```

We set `CONFIGS_DIR=/app/configs` as a default so the engineer doesn't have to remember to pass it.

- [ ] **Step 3: Build the image**

```bash
docker build -f api/Dockerfile -t spicy-desi-api:local .
```

(Run from repo root, not from `api/`.)

Expected: successful build.

- [ ] **Step 4: Boot test**

```bash
docker run --rm -d --name spicy-api-test -p 18080:8080 \
  -e TOOLS_SHARED_SECRET="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -e SQUARE_ACCESS_TOKEN="test" \
  -e SQUARE_ENVIRONMENT="sandbox" \
  -e SQUARE_WEBHOOK_SIGNATURE_KEY="test" \
  spicy-desi-api:local
sleep 3
curl -fsS http://localhost:18080/healthz
docker rm -f spicy-api-test
```

Expected: prints `{"ok":true}`.

- [ ] **Step 5: Commit**

```bash
git add api/Dockerfile api/.dockerignore
git commit -m "feat(api): add Dockerfile (build from repo root so configs/ can be copied in)

Build: docker build -f api/Dockerfile -t spicy-desi-api:local .
Default CONFIGS_DIR=/app/configs so engineer doesn't need to set it."
```

---

### Task 3.4: docker-compose for local integration

**Files:**
- Create: `docker-compose.yml` (at repo root)
- Create: `.env.example` (at repo root, documents the env surface)

- [ ] **Step 1: Write `.env.example`**

Create `.env.example` at repo root:

```bash
# === Shared ===
TOOLS_SHARED_SECRET=replace-with-32-byte-random-string-xxxxxxxxxxxxx

# === API ===
SQUARE_ACCESS_TOKEN=your-square-access-token
SQUARE_ENVIRONMENT=sandbox
SQUARE_WEBHOOK_SIGNATURE_KEY=your-square-webhook-key
SQUARE_WEBHOOK_URL=https://api.spicydesichicago.com/api/webhooks/square
SQUARE_SPECIALS_CATEGORY_ID=SPECIALS
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
AGENT_PUBLIC_URL=https://agent.spicydesichicago.com
CORS_ORIGINS=https://spicydesichicago.com

# === Agent ===
TOOLS_API_BASE=http://api:8080
GROQ_API_KEY=your-groq-key
DEEPGRAM_API_KEY=your-deepgram-key
CARTESIA_API_KEY=your-cartesia-key
CARTESIA_VOICE_ID=your-cartesia-voice-id
LLM_MODEL=llama-3.3-70b-versatile
# Optional OpenAI-compatible endpoint override:
# LLM_BASE_URL=
# LLM_API_KEY=
```

- [ ] **Step 2: Write `docker-compose.yml`**

Create `docker-compose.yml` at repo root:

```yaml
services:
  api:
    build:
      context: .
      dockerfile: api/Dockerfile
    image: spicy-desi-api:local
    ports:
      - "8080:8080"
    environment:
      TOOLS_SHARED_SECRET: ${TOOLS_SHARED_SECRET}
      SQUARE_ACCESS_TOKEN: ${SQUARE_ACCESS_TOKEN}
      SQUARE_ENVIRONMENT: ${SQUARE_ENVIRONMENT}
      SQUARE_WEBHOOK_SIGNATURE_KEY: ${SQUARE_WEBHOOK_SIGNATURE_KEY}
      SQUARE_WEBHOOK_URL: ${SQUARE_WEBHOOK_URL:-}
      SQUARE_SPECIALS_CATEGORY_ID: ${SQUARE_SPECIALS_CATEGORY_ID:-SPECIALS}
      TWILIO_ACCOUNT_SID: ${TWILIO_ACCOUNT_SID:-}
      TWILIO_AUTH_TOKEN: ${TWILIO_AUTH_TOKEN:-}
      TWILIO_FROM_NUMBER: ${TWILIO_FROM_NUMBER:-}
      AGENT_PUBLIC_URL: ${AGENT_PUBLIC_URL:-}
      CORS_ORIGINS: ${CORS_ORIGINS:-https://spicydesichicago.com}
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/healthz').status==200 else 1)"]
      interval: 10s
      timeout: 3s
      retries: 3

  agent:
    build:
      context: ./agent
      dockerfile: Dockerfile
    image: spicy-desi-agent:local
    ports:
      - "8090:8090"
    depends_on:
      api:
        condition: service_healthy
    environment:
      TOOLS_API_BASE: http://api:8080
      TOOLS_SHARED_SECRET: ${TOOLS_SHARED_SECRET}
      GROQ_API_KEY: ${GROQ_API_KEY}
      DEEPGRAM_API_KEY: ${DEEPGRAM_API_KEY}
      CARTESIA_API_KEY: ${CARTESIA_API_KEY}
      CARTESIA_VOICE_ID: ${CARTESIA_VOICE_ID}
      LLM_MODEL: ${LLM_MODEL:-llama-3.3-70b-versatile}
      LLM_BASE_URL: ${LLM_BASE_URL:-}
      LLM_API_KEY: ${LLM_API_KEY:-}
      TWILIO_AUTH_TOKEN: ${TWILIO_AUTH_TOKEN:-}
```

- [ ] **Step 3: Test compose (skip if you don't want to wait for full builds)**

```bash
cp .env.example .env.local
# Edit .env.local with at least placeholder values; for boot test:
sed -i.bak 's/your-square-access-token/test-token/; s/your-square-webhook-key/test-key/; s/your-groq-key/test/; s/your-deepgram-key/test/; s/your-cartesia-key/test/; s/your-cartesia-voice-id/test-voice/' .env.local
docker compose --env-file .env.local up -d --build
sleep 8
curl -fsS http://localhost:8080/healthz
curl -fsS http://localhost:8090/healthz
docker compose down
rm -f .env.local .env.local.bak
```

Expected: both `{"ok":true}` responses.

- [ ] **Step 4: Add `.env.local` and `.env` to `.gitignore`**

```bash
grep -qE "^\.env\.local$" .gitignore || echo ".env.local" >> .gitignore
grep -qE "^\.env$" .gitignore || echo ".env" >> .gitignore
```

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .env.example .gitignore
git commit -m "feat: docker-compose + .env.example for local integration testing

Both services boot under compose; agent depends on api healthcheck.
.env.example documents the full required env surface."
```

---

### Task 3.5: Run full test suite again to confirm Docker work didn't touch app code

**Files:** None.

- [ ] **Step 1: Run agent tests**

```bash
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -10)
```

Expected: all pass.

- [ ] **Step 2: Run API tests**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -10)
```

Expected: all pass.

---

## Phase 4 — Fly.io configuration

### Task 4.1: Create Fly apps

**Files:** None (Fly-side resources).

- [ ] **Step 1: Create the API app**

```bash
flyctl apps create spicy-desi-api --org personal
```

If the name is taken, append a suffix (e.g. `spicy-desi-api-prod`) and use that everywhere below. Confirm:

```bash
flyctl apps list | grep spicy-desi
```

- [ ] **Step 2: Create the agent app**

```bash
flyctl apps create spicy-desi-agent --org personal
```

(Same fallback if name is taken.)

- [ ] **Step 3: Record the chosen names**

If you had to use fallback names, note them. The plan assumes `spicy-desi-api` and `spicy-desi-agent` — substitute throughout if needed.

---

### Task 4.2: Write `api/fly.toml`

**Files:**
- Create: `api/fly.toml`

**Build context note:** The api Dockerfile needs the repo root as build context (it does `COPY configs ./configs`). We achieve this by running `flyctl deploy --config api/fly.toml --dockerfile api/Dockerfile` from the **repo root** — Fly uses the current directory as build context. The fly.toml itself stays minimal and avoids hardcoding any path; the CLI flags handle it.

- [ ] **Step 1: Create `api/fly.toml`**

```toml
app = "spicy-desi-api"
primary_region = "ord"

[env]
  PORT = "8080"
  LOG_LEVEL = "info"
  APP_ENV = "production"
  CONFIGS_DIR = "/app/configs"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = false
  auto_start_machines = true
  min_machines_running = 1

  [http_service.concurrency]
    type = "connections"
    soft_limit = 50
    hard_limit = 100

  [[http_service.checks]]
    grace_period = "10s"
    interval = "30s"
    method = "GET"
    timeout = "5s"
    path = "/healthz"

[[vm]]
  size = "shared-cpu-1x"
  memory = "256mb"
```

(Modern `[http_service]` style — Fly's recommended block for HTTP apps.)

- [ ] **Step 2: Validate the TOML**

```bash
flyctl config validate --config api/fly.toml
```

Expected: "Configuration is valid".

---

### Task 4.3: Write `agent/fly.toml`

**Files:**
- Create: `agent/fly.toml`

- [ ] **Step 1: Create the file**

```toml
app = "spicy-desi-agent"
primary_region = "ord"

[env]
  PORT = "8090"
  LOG_LEVEL = "info"

[http_service]
  internal_port = 8090
  force_https = true
  auto_stop_machines = false
  auto_start_machines = true
  min_machines_running = 1

  [http_service.concurrency]
    type = "connections"
    soft_limit = 25
    hard_limit = 50

  [[http_service.checks]]
    grace_period = "15s"
    interval = "30s"
    method = "GET"
    timeout = "5s"
    path = "/healthz"

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

(Agent gets 512MB instead of 256MB — Pipecat + LLM streaming needs more headroom than the REST API.)

- [ ] **Step 2: Validate**

```bash
flyctl config validate --config agent/fly.toml
```

Expected: "Configuration is valid".

- [ ] **Step 3: Commit both fly.tomls**

```bash
git add api/fly.toml agent/fly.toml
git commit -m "feat: fly.toml for api and agent (Chicago region, force_https, /healthz)"
```

---

### Task 4.4: Set Fly secrets

**Files:** None.

- [ ] **Step 1: Generate a strong tools shared secret**

```bash
TOOLS_SECRET=$(openssl rand -hex 32)
echo "TOOLS_SHARED_SECRET=$TOOLS_SECRET"
```

Save this value — both apps need the same one.

- [ ] **Step 2: Set API secrets**

Replace placeholder values with real ones. You'll need: Square access token (live), Square webhook signature key (live), Twilio Account SID, Twilio Auth Token, Twilio From number.

```bash
flyctl secrets set --app spicy-desi-api \
  TOOLS_SHARED_SECRET="$TOOLS_SECRET" \
  SQUARE_ACCESS_TOKEN="<real-square-token>" \
  SQUARE_ENVIRONMENT="production" \
  SQUARE_WEBHOOK_SIGNATURE_KEY="<real-square-webhook-key>" \
  SQUARE_WEBHOOK_URL="https://api.spicydesichicago.com/api/webhooks/square" \
  TWILIO_ACCOUNT_SID="<real-twilio-sid>" \
  TWILIO_AUTH_TOKEN="<real-twilio-token>" \
  TWILIO_FROM_NUMBER="<real-twilio-number>" \
  AGENT_PUBLIC_URL="https://agent.spicydesichicago.com" \
  CORS_ORIGINS="https://spicydesichicago.com"
```

Expected: "Secrets are staged for the first deployment".

- [ ] **Step 3: Set agent secrets**

```bash
flyctl secrets set --app spicy-desi-agent \
  TOOLS_API_BASE="http://spicy-desi-api.flycast:8080" \
  TOOLS_SHARED_SECRET="$TOOLS_SECRET" \
  GROQ_API_KEY="<real-groq-key>" \
  DEEPGRAM_API_KEY="<real-deepgram-key>" \
  CARTESIA_API_KEY="<real-cartesia-key>" \
  CARTESIA_VOICE_ID="<real-cartesia-voice-id>" \
  TWILIO_AUTH_TOKEN="<real-twilio-token>"
```

Note: `TOOLS_API_BASE` uses `.flycast` for internal Fly DNS — the agent calls the api over Fly's private WireGuard network. No public-internet round-trip, no TLS, free.

- [ ] **Step 4: Verify secret names landed (not values)**

```bash
flyctl secrets list --app spicy-desi-api
flyctl secrets list --app spicy-desi-agent
```

Expected: lists each secret by name with a digest.

---

## Phase 5 — Deploy

### Task 5.1: Deploy API

**Files:** None.

- [ ] **Step 1: Deploy from repo root (so Docker context includes `configs/`)**

```bash
flyctl deploy --config api/fly.toml --dockerfile api/Dockerfile
```

Expected: builds image, pushes to Fly registry, releases v1, machine becomes healthy. Tail of output should show `1 desired, 1 placed, 1 healthy`.

If the build fails:
- "COPY configs ./configs" failing → ensure you ran `flyctl deploy` from the repo root, not from `api/`.
- Module import errors → ensure `pyproject.toml` matches what's installed.

- [ ] **Step 2: Smoke test deployed API**

```bash
curl -fsS https://spicy-desi-api.fly.dev/healthz
```

Expected: `{"ok":true}`.

- [ ] **Step 3: Test a real endpoint (locations, anonymous)**

```bash
curl -fsS https://spicy-desi-api.fly.dev/api/locations
```

Expected: returns location data from Square (real, since we set real `SQUARE_ACCESS_TOKEN`). If it errors, check `flyctl logs --app spicy-desi-api`.

---

### Task 5.2: Deploy Agent

**Files:** None.

- [ ] **Step 1: Deploy from inside `agent/`**

The agent Dockerfile uses `agent/` as build context (it has no need for `configs/`), so deploy from there:

```bash
(cd agent && flyctl deploy --config fly.toml)
```

Expected: image build (longer than API — Pipecat is heavy), push, release, healthy.

- [ ] **Step 2: Smoke test agent**

```bash
curl -fsS https://spicy-desi-agent.fly.dev/healthz
```

Expected: `{"ok":true}`.

- [ ] **Step 3: Verify agent→API internal connectivity via logs**

Watch agent logs while curling something that would force an API call. Or, simpler: SSH into the agent machine and curl the internal URL.

```bash
flyctl ssh console --app spicy-desi-agent --command "curl -fsS http://spicy-desi-api.flycast:8080/healthz"
```

Expected: `{"ok":true}` — proves the internal `.flycast` DNS resolves and traffic flows.

---

### Task 5.3: Add custom domains and TLS certificates

**Files:** None.

- [ ] **Step 1: Add domain to API**

```bash
flyctl certs add api.spicydesichicago.com --app spicy-desi-api
```

Fly outputs the DNS records you need to create.

- [ ] **Step 2: Add domain to Agent**

```bash
flyctl certs add agent.spicydesichicago.com --app spicy-desi-agent
```

- [ ] **Step 3: Add DNS records at your domain registrar**

At your DNS provider for `spicydesichicago.com`, add:

```
api.spicydesichicago.com    CNAME    spicy-desi-api.fly.dev
agent.spicydesichicago.com  CNAME    spicy-desi-agent.fly.dev
```

Wait 1–10 minutes for propagation.

- [ ] **Step 4: Verify cert issuance**

```bash
flyctl certs show api.spicydesichicago.com --app spicy-desi-api
flyctl certs show agent.spicydesichicago.com --app spicy-desi-agent
```

Both should show "Certificate is valid" once Let's Encrypt completes the challenge.

- [ ] **Step 5: Hit the custom domain**

```bash
curl -fsS https://api.spicydesichicago.com/healthz
curl -fsS https://agent.spicydesichicago.com/healthz
```

Expected: both `{"ok":true}`.

---

### Task 5.4: Point Twilio at the new agent URL

**Files:** None (Twilio console).

- [ ] **Step 1: Open Twilio Phone Numbers console**

Go to https://console.twilio.com/us1/develop/phone-numbers/manage/incoming

- [ ] **Step 2: Select your Spicy Desi number**

Find the number listed in `configs/spicy-desi/tenant.json` `twilio_number`.

- [ ] **Step 3: Update "A CALL COMES IN" webhook**

Set it to:

```
URL:    https://agent.spicydesichicago.com/twilio/inbound
Method: HTTP POST
```

Save.

---

## Phase 6 — End-to-end live validation

### Task 6.1: First live inbound call test

**Files:** None.

- [ ] **Step 1: Tail logs from both services**

In one terminal:

```bash
flyctl logs --app spicy-desi-agent
```

In another:

```bash
flyctl logs --app spicy-desi-api
```

- [ ] **Step 2: Call the Twilio number**

From your cell phone, dial the Spicy Desi Twilio number.

- [ ] **Step 3: Verify the call flow**

Expected:
- Agent picks up within ~1 second
- Greeting plays cleanly
- You can ask "what's on the menu?" — agent should call `list_menu_categories` → API logs show the call → agent reads back categories
- You can ask for hours — agent should call `get_pickup_today` → API logs show the call → agent reads the hours
- You can say "connect me to the owner" — agent should respond "Hold on — connecting you to the owner now" and the call should dial the owner phone (or fall through to take-message if owner isn't available)
- Hang up cleanly

- [ ] **Step 4: Check for signature-validation failures**

In agent logs, look for any `403 invalid twilio signature` lines. If you see them, Twilio's webhook is being rejected — most likely cause is the URL Twilio signed doesn't match what FastAPI reconstructs. Debugging:

```bash
flyctl ssh console --app spicy-desi-agent
# inside:
env | grep TWILIO_AUTH_TOKEN  # confirm it's set
```

If `TWILIO_AUTH_TOKEN` is unset, signature validation is in dev-mode and accepts everything — that's why no 403s. If it IS set and you see 403s, the URL reconstruction is wrong; see the `_full_url` helper in `agent/app/server.py` and confirm `--proxy-headers` is on the uvicorn command in the Dockerfile (it is).

- [ ] **Step 5: Document any issues**

If anything misbehaves, capture the log excerpt. Common issues:
- Cold start delay (>2s before greeting) — Fly should keep the machine warm with `min_machines_running = 1`
- Bad audio quality — check Cartesia voice id and region (`primary_region = "ord"` should be close to Chicago)
- Tool calls failing with 401 — `TOOLS_SHARED_SECRET` must match exactly between the two apps

---

### Task 6.2: Verify no test regressions

**Files:** None.

- [ ] **Step 1: Re-run agent tests**

```bash
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -10)
```

Expected: all pass.

- [ ] **Step 2: Re-run API tests**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -10)
```

Expected: all pass.

---

### Task 6.3: Update root README with deploy summary

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append a "Deployment" section to README.md**

Add a new section (preserve existing content):

```markdown
## Deployment

Both services run on Fly.io (free tier, region: ord).

### Production URLs
- API: `https://api.spicydesichicago.com`
- Agent: `https://agent.spicydesichicago.com`

### Deploy commands

```bash
# API (build context = repo root so configs/ is included)
flyctl deploy --config api/fly.toml --dockerfile api/Dockerfile

# Agent (build context = agent/)
(cd agent && flyctl deploy --config fly.toml)
```

### Twilio configuration
The phone number's "A CALL COMES IN" webhook points at
`https://agent.spicydesichicago.com/twilio/inbound` (POST).

### Security
- All Twilio webhooks validated via `X-Twilio-Signature` HMAC (controlled
  by `TWILIO_AUTH_TOKEN` env on agent). Empty token = dev-mode bypass.
- Square webhook validated via `X-Square-HmacSha256-Signature`.
- CORS pinned to `https://spicydesichicago.com`.
- Agent → API traffic uses Fly's internal `.flycast` DNS over WireGuard.

### Local development with Docker

```bash
cp .env.example .env.local
# Fill in .env.local with real values
docker compose --env-file .env.local up --build
```

Agent at `http://localhost:8090`, API at `http://localhost:8080`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: deployment section (Fly.io, custom domains, security model)"
```

---

## Phase 7 — Open the PR

### Task 7.1: Push and open PR

**Files:** None.

- [ ] **Step 1: Push branch**

```bash
git push -u origin feature/fly-deploy-and-security
```

- [ ] **Step 2: Open PR via gh**

```bash
gh pr create --base main --title "feat: Fly.io deploy + Twilio signature validation" --body "$(cat <<'EOF'
## Summary
- Dockerize both `agent` and `api` services (Python 3.12, multi-stage, slim runtime)
- Deploy both to Fly.io behind custom domains `agent.spicydesichicago.com` and `api.spicydesichicago.com`
- Enforce `X-Twilio-Signature` validation on all three agent webhook routes (`/twilio/inbound`, `/twilio/dial-owner`, `/twilio/dial-owner-fallback`) with a dev-mode bypass when `TWILIO_AUTH_TOKEN` is empty
- Internal agent→API traffic uses Fly's `.flycast` private DNS

## What this does NOT include (separate plans)
- Firebase RTDB persistence layer
- Firebase Auth ID tokens for dashboard
- slowapi rate limiting
- Voice fallback lines on tool errors

## Test plan
- [x] 59 unit + integration tests pass locally (`pytest agent/tests api/tests`)
- [x] Both Docker images build and respond to `/healthz` locally
- [x] `docker compose up` boots both services and they reach each other
- [x] Fly TOML validates (`flyctl config validate`)
- [x] Both services deploy and `/healthz` responds on `.fly.dev` URLs
- [x] Custom domain TLS certs issued
- [x] `agent → api` traffic works over `.flycast` (verified via `flyctl ssh console`)
- [x] Real Twilio inbound call: greeting plays, menu/hours tool calls succeed, owner-transfer works, hang-up clean
- [x] Twilio signature validation: agent rejects unsigned POST with 403

EOF
)"
```

Expected: prints the PR URL.

- [ ] **Step 3: Note the PR URL**

Capture the URL for follow-up.

---

## Verification (the whole plan, end-to-end)

After all phases:

1. **Tests pass everywhere**:
   ```bash
   (cd agent && .venv/bin/pytest tests/ -q)
   (cd api && .venv/bin/pytest tests/ -q)
   ```
2. **Both services healthy on Fly**:
   ```bash
   curl -fsS https://api.spicydesichicago.com/healthz
   curl -fsS https://agent.spicydesichicago.com/healthz
   ```
3. **Real call works end-to-end**: dial the Twilio number, exercise menu/hours/transfer.
4. **Unsigned attacks blocked**:
   ```bash
   curl -i -X POST https://agent.spicydesichicago.com/twilio/inbound -d "From=%2B15551234567"
   ```
   Expected: HTTP/2 403.
5. **No regressions in `feature/oracle-deploy`** — the existing Oracle deploy artifacts remain untouched on that branch.

---

## What's next (separate plans, do NOT include here)

- **Plan 2: Firebase RTDB persistence** — refactor `event_log.py` / `pickup_state.py` to write to Firebase RTDB; provide dashboard schema doc.
- **Plan 3: Voice fallback lines + reliable event retry** — Tier 0 items 0.1 + 0.2 from the roadmap.
- **Plan 4: Dashboard auth + rate limiting + Firebase Auth ID tokens** — finish the rest of 0.0c.

Each is independently testable and shouldn't be bundled into this PR.
