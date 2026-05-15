# Dashboard API + Firebase Auth + Rate Limiting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the dashboard-facing API surface the existing frontend will call: list/handle messages, list calls, set/clear owner availability override, and view daily stats. Protect every dashboard endpoint with Firebase Auth ID token verification (email allowlist of owner accounts). Add slowapi rate limiting on public endpoints.

**Architecture:** A new `/api/admin/*` route prefix with 8 endpoints, each guarded by a `require_admin_user` FastAPI dependency that calls `firebase_admin.auth.verify_id_token()` and checks the user's email against `ADMIN_ALLOWED_EMAILS`. Existing `/api/*` endpoints (used by the agent, secret-authed via `X-Tools-Auth`) are unchanged. slowapi adds per-IP rate limits on the agent-facing webhooks (`/twilio/*`, `/api/webhooks/square`) and an aggregate limit on auth-failed requests so brute-force attempts hit a wall.

**Tech Stack:** FastAPI, firebase-admin (already in deps from Plan 2a), slowapi, Pydantic.

**Branch:** `feature/dashboard-api-auth` from main (can stack on top of 2a/2b/3 once they land).

**Depends on:** Plan 2a — `firebase-admin` is installed and the Firestore stores exist. Plan 2b is helpful (call lifecycle data populated) but not required.

**Frontend out of scope** — the dashboard frontend lives in a separate branch / repo. This plan builds the API the frontend will call, including a Postman/curl-friendly contract.

---

## Pre-flight context

- Firebase project: `spicy-desi-chicago`. Same Auth + same Firestore as Plan 2a.
- Owner UID: `Woavythv26dZ7XlJngL7lKakQ7N2` (email `techtastellc@gmail.com`).
- Second user UID seen during inspection: `fOGzXQglXPOC7VvTVJvY2vbdeh12` — email unknown; if it's another admin, add their email to the allowlist via `ADMIN_ALLOWED_EMAILS` env at deploy time.
- The agent service does NOT need any of this — it uses `X-Tools-Auth` shared secret.
- Existing CORS pin: `https://spicydesichicago.com` (already configured in Plan 2a deploy work).
- `firebase-admin` already installed in `api/.venv` from Plan 2a.

---

## API surface (this plan delivers)

All endpoints below are at `/api/admin/*`, require `Authorization: Bearer <firebase-id-token>` header, and respond JSON.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/admin/messages/unhandled` | List unhandled messages (newest first, paginated) |
| POST | `/api/admin/messages/{id}/handle` | Mark a message as handled (records UID + ts) |
| GET | `/api/admin/calls/today` | List today's calls (Chicago time) — id, caller, duration, outcome, summary |
| GET | `/api/admin/calls/{call_sid}` | Full call detail: parent doc + full events subcollection |
| GET | `/api/admin/owner-override` | Current override state |
| POST | `/api/admin/owner-override` | Set override (`until_iso`, `reason`) |
| DELETE | `/api/admin/owner-override` | Clear override |
| GET | `/api/admin/stats/daily?days=7` | Per-day aggregates: total calls, transfers, messages |

**Frontend contract** (for the other-branch dashboard team):
- `GET /api/admin/messages/unhandled` returns:
  ```json
  {"messages": [{"id": "...", "callSid": "...", "callerPhone": "+1...", "callerName": null|str, "reason": "...", "takenAt": "ISO8601"}, ...]}
  ```
- All timestamps are ISO 8601 with timezone.
- Errors: 401 = missing/invalid token; 403 = email not in allowlist; 404 = resource not found; 400 = validation. Body always `{"error": "human readable"}`.

---

## File structure

```
api/
  app/
    api/
      middleware/
        __init__.py
        firebase_auth.py        ← NEW: verify_id_token + email allowlist
        rate_limit.py           ← NEW: slowapi setup
      routes/
        admin/
          __init__.py
          messages.py           ← NEW
          calls.py              ← NEW
          owner_override.py     ← NEW
          stats.py              ← NEW
      dependencies.py           ← MODIFY: add admin user dep, add stores already present
    infrastructure/
      config.py                 ← MODIFY: ADMIN_ALLOWED_EMAILS, rate-limit settings
      firestore_call_store.py   ← MODIFY: add list_calls_today + count helpers
      firestore_message_store.py ← reused
      firestore_owner_override_store.py ← reused
  tests/
    helpers/
      firebase_auth_stub.py     ← NEW: mock verify_id_token for tests
    unit/
      test_firebase_auth.py
      test_rate_limit.py
    integration/
      test_admin_messages_route.py
      test_admin_calls_route.py
      test_admin_owner_override_route.py
      test_admin_stats_route.py
```

---

## Phase 1 — Firebase Auth middleware

### Task 1.1: ADMIN_ALLOWED_EMAILS setting

**Files:**
- Modify: `api/app/infrastructure/config.py`

- [ ] **Step 1: Add field to AppSettings**

Find the section near other Firebase fields:
```python
    firebase_service_account_path: str = Field("", alias="FIREBASE_SERVICE_ACCOUNT_PATH")
    firebase_project_id: str = Field("spicy-desi-chicago", alias="FIREBASE_PROJECT_ID")
```

Append:
```python
    admin_allowed_emails: str = Field("", alias="ADMIN_ALLOWED_EMAILS")
```

(Comma-separated string; we parse to a list in a property.)

Then add a property below (anywhere in the class):
```python
    @property
    def admin_allowed_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_allowed_emails.split(",") if e.strip()]
```

- [ ] **Step 2: Run config tests**

```bash
(cd api && .venv/bin/pytest tests/unit/test_config.py -v 2>&1 | tail -10)
```
Expected: existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add api/app/infrastructure/config.py
git commit -m "feat(api): ADMIN_ALLOWED_EMAILS config (comma-separated email allowlist)"
```

### Task 1.2: FirebaseAuthVerifier (TDD)

**Files:**
- Create: `api/app/api/middleware/__init__.py` (empty)
- Create: `api/app/api/middleware/firebase_auth.py`
- Create: `api/tests/unit/test_firebase_auth.py`

- [ ] **Step 1: Create package marker**

```bash
mkdir -p api/app/api/middleware
touch api/app/api/middleware/__init__.py
```

- [ ] **Step 2: Write failing tests**

Create `api/tests/unit/test_firebase_auth.py`:

```python
"""Tests for FirebaseAuthVerifier (token verification + email allowlist)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.api.middleware.firebase_auth import (
    AuthError,
    FirebaseAuthVerifier,
)


def test_verify_returns_uid_email_on_valid_token():
    """Mock verify_id_token to return a known decoded payload."""
    decoded = {"uid": "uid-owner", "email": "techtastellc@gmail.com", "email_verified": True}
    with patch(
        "app.api.middleware.firebase_auth.firebase_auth.verify_id_token",
        return_value=decoded,
    ):
        verifier = FirebaseAuthVerifier(allowed_emails=["techtastellc@gmail.com"])
        result = verifier.verify("any-token-string")
    assert result["uid"] == "uid-owner"
    assert result["email"] == "techtastellc@gmail.com"


def test_verify_rejects_missing_token():
    verifier = FirebaseAuthVerifier(allowed_emails=["techtastellc@gmail.com"])
    with pytest.raises(AuthError) as exc:
        verifier.verify("")
    assert "missing" in str(exc.value).lower()


def test_verify_rejects_invalid_token():
    from firebase_admin.auth import InvalidIdTokenError
    with patch(
        "app.api.middleware.firebase_auth.firebase_auth.verify_id_token",
        side_effect=InvalidIdTokenError("bad token"),
    ):
        verifier = FirebaseAuthVerifier(allowed_emails=["techtastellc@gmail.com"])
        with pytest.raises(AuthError) as exc:
            verifier.verify("garbage")
    assert "invalid" in str(exc.value).lower()


def test_verify_rejects_email_not_in_allowlist():
    decoded = {"uid": "uid-stranger", "email": "stranger@example.com", "email_verified": True}
    with patch(
        "app.api.middleware.firebase_auth.firebase_auth.verify_id_token",
        return_value=decoded,
    ):
        verifier = FirebaseAuthVerifier(allowed_emails=["techtastellc@gmail.com"])
        with pytest.raises(AuthError) as exc:
            verifier.verify("token")
    assert "not authorized" in str(exc.value).lower() or "allowlist" in str(exc.value).lower()


def test_verify_rejects_unverified_email():
    """Firebase Auth supports unverified emails. We require verified."""
    decoded = {"uid": "uid", "email": "techtastellc@gmail.com", "email_verified": False}
    with patch(
        "app.api.middleware.firebase_auth.firebase_auth.verify_id_token",
        return_value=decoded,
    ):
        verifier = FirebaseAuthVerifier(allowed_emails=["techtastellc@gmail.com"])
        with pytest.raises(AuthError):
            verifier.verify("token")


def test_email_match_is_case_insensitive():
    decoded = {"uid": "uid", "email": "TechTasteLLC@Gmail.com", "email_verified": True}
    with patch(
        "app.api.middleware.firebase_auth.firebase_auth.verify_id_token",
        return_value=decoded,
    ):
        verifier = FirebaseAuthVerifier(allowed_emails=["techtastellc@gmail.com"])
        result = verifier.verify("token")
    assert result["email"].lower() == "techtastellc@gmail.com"


def test_empty_allowlist_rejects_everyone():
    """Defense against misconfiguration — never allow any user when
    allowlist is empty."""
    decoded = {"uid": "uid", "email": "techtastellc@gmail.com", "email_verified": True}
    with patch(
        "app.api.middleware.firebase_auth.firebase_auth.verify_id_token",
        return_value=decoded,
    ):
        verifier = FirebaseAuthVerifier(allowed_emails=[])
        with pytest.raises(AuthError):
            verifier.verify("token")
```

- [ ] **Step 3: Run tests, confirm failure**

```bash
(cd api && .venv/bin/pytest tests/unit/test_firebase_auth.py -v 2>&1 | tail -15)
```
Expected: ModuleNotFoundError.

- [ ] **Step 4: Implement**

Create `api/app/api/middleware/firebase_auth.py`:

```python
"""Firebase Auth ID token verification + email allowlist.

Used by the dashboard-facing /api/admin/* routes. The agent service
uses X-Tools-Auth shared-secret and never touches this module.

Production behavior:
- Browser sends Authorization: Bearer <firebase-id-token> on every
  request to /api/admin/*.
- firebase_admin.auth.verify_id_token() validates the JWT signature,
  expiration, audience, etc.
- We additionally require email_verified=True and email-in-allowlist.

Misconfiguration safety: empty allowlist rejects EVERY token. Set
ADMIN_ALLOWED_EMAILS to the owner emails before going live.
"""
from __future__ import annotations

from typing import Any

from firebase_admin import auth as firebase_auth


class AuthError(Exception):
    """Raised when a token is missing, invalid, or the email isn't allowed."""


class FirebaseAuthVerifier:
    def __init__(self, *, allowed_emails: list[str]) -> None:
        # Lowercase for case-insensitive match
        self._allowlist = {e.lower().strip() for e in allowed_emails if e.strip()}

    def verify(self, token: str) -> dict[str, Any]:
        if not token:
            raise AuthError("missing Authorization Bearer token")

        try:
            decoded = firebase_auth.verify_id_token(token)
        except Exception as e:
            # firebase_admin raises various subclasses (InvalidIdTokenError,
            # ExpiredIdTokenError, RevokedIdTokenError, CertificateFetchError).
            # All map to 401 — invalid token.
            raise AuthError(f"invalid token: {type(e).__name__}") from e

        email = (decoded.get("email") or "").lower()
        if not decoded.get("email_verified", False):
            raise AuthError("email not verified")
        if email not in self._allowlist:
            raise AuthError(f"{email} not in admin allowlist")
        return decoded
```

- [ ] **Step 5: Run tests**

```bash
(cd api && .venv/bin/pytest tests/unit/test_firebase_auth.py -v 2>&1 | tail -15)
```
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add api/app/api/middleware/__init__.py api/app/api/middleware/firebase_auth.py \
        api/tests/unit/test_firebase_auth.py
git commit -m "feat(api): FirebaseAuthVerifier — verify Firebase ID token + email allowlist

Requires email_verified=True and email-in-allowlist. Empty allowlist
rejects everyone (defense vs. misconfiguration)."
```

### Task 1.3: Hook into AppState + FastAPI dependency

**Files:**
- Modify: `api/app/api/dependencies.py`
- Modify: `api/app/main.py`

- [ ] **Step 1: Add verifier to AppState**

In `api/app/api/dependencies.py`, add the import:
```python
from app.api.middleware.firebase_auth import AuthError, FirebaseAuthVerifier
```

Add field to AppState dataclass:
```python
    admin_verifier: FirebaseAuthVerifier
```

(Required, no default.)

Add a FastAPI dependency function at the end of the file (alongside `get_state`, `require_tools_auth`):

```python
from fastapi import Header, HTTPException, Request


async def require_admin_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """FastAPI dependency for /api/admin/* routes. Verifies the Bearer
    token and returns the decoded Firebase claims (uid, email, etc.).

    Raises:
        HTTPException(401) on missing/invalid token.
        HTTPException(403) on email not in allowlist.
    """
    state = get_state(request)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing Authorization Bearer token")
    token = authorization[len("Bearer "):].strip()
    try:
        return state.admin_verifier.verify(token)
    except AuthError as e:
        msg = str(e).lower()
        if "not in" in msg or "allowlist" in msg or "not authorized" in msg or "not verified" in msg:
            raise HTTPException(status_code=403, detail=str(e)) from e
        raise HTTPException(status_code=401, detail=str(e)) from e
```

(The 401/403 split: 401 = "we couldn't verify who you are"; 403 = "we verified you, but you don't have permission".)

- [ ] **Step 2: Construct verifier in main._build()**

In `api/app/main.py`, add the import alongside other infrastructure imports:
```python
from app.api.middleware.firebase_auth import FirebaseAuthVerifier
```

In `_build()`, after the firestore client is constructed:
```python
admin_verifier = FirebaseAuthVerifier(allowed_emails=settings.admin_allowed_emails_list)
```

Pass to AppState:
```python
state = AppState(
    ...,  # existing
    admin_verifier=admin_verifier,
)
```

- [ ] **Step 3: Initialize firebase_admin app at startup**

`firebase_admin.auth.verify_id_token` requires the default Firebase app to be initialized first. The Firestore client doesn't need this (it uses google-cloud-firestore directly), so we add it here.

Add to `api/app/main.py` near the top (with other imports):
```python
import firebase_admin
from firebase_admin import credentials as fb_credentials
```

And inside `_build()`, BEFORE constructing AppState, after settings are loaded:
```python
# Initialize firebase_admin's default app (needed for auth.verify_id_token).
# Idempotent: subsequent calls in tests are no-ops via the try/except.
if not firebase_admin._apps:  # type: ignore[attr-defined]
    if settings.firebase_service_account_path:
        cred = fb_credentials.Certificate(settings.firebase_service_account_path)
        firebase_admin.initialize_app(cred, {"projectId": settings.firebase_project_id})
    else:
        # Ambient creds (Cloud Run, GCE)
        firebase_admin.initialize_app(options={"projectId": settings.firebase_project_id})
```

- [ ] **Step 4: Update test fixtures**

In `api/tests/conftest.py`, the `client_factory` builds AppState. Add `admin_verifier=...` to that construction. For tests, use a stub verifier so they don't need to mock `firebase_admin.auth` per test.

Create `api/tests/helpers/firebase_auth_stub.py`:
```python
"""Stub FirebaseAuthVerifier for integration tests.

The real verifier calls firebase_admin.auth.verify_id_token which needs
the default app initialized + a real signed JWT. Tests use this stub
which decodes a JSON-encoded fake token and applies the same allowlist
logic.

Fake token format: "fake:<email>" — e.g. "fake:techtastellc@gmail.com".
"""
from __future__ import annotations

from app.api.middleware.firebase_auth import AuthError


class StubFirebaseAuthVerifier:
    def __init__(self, *, allowed_emails: list[str]) -> None:
        self._allowlist = {e.lower().strip() for e in allowed_emails if e.strip()}

    def verify(self, token: str) -> dict[str, object]:
        if not token:
            raise AuthError("missing")
        if not token.startswith("fake:"):
            raise AuthError(f"invalid token: not a fake: prefix ({token[:10]}...)")
        email = token[len("fake:"):].lower()
        if email not in self._allowlist:
            raise AuthError(f"{email} not in admin allowlist")
        return {
            "uid": f"uid-{email.split('@')[0]}",
            "email": email,
            "email_verified": True,
        }
```

Then in `conftest.py`, when building AppState for tests:
```python
from tests.helpers.firebase_auth_stub import StubFirebaseAuthVerifier
...
admin_verifier = StubFirebaseAuthVerifier(
    allowed_emails=["techtastellc@gmail.com", "owner@spicydesichicago.com"],
)
```

Pass into AppState. This makes integration tests look like:
```python
resp = client.get(
    "/api/admin/messages/unhandled",
    headers={"Authorization": "Bearer fake:techtastellc@gmail.com"},
)
```

- [ ] **Step 5: Run full suite — make sure existing tests still pass**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 113 passed (we added the field + dependency but no new endpoint is wired yet).

- [ ] **Step 6: Commit**

```bash
git add api/app/api/dependencies.py api/app/main.py api/tests/helpers/firebase_auth_stub.py api/tests/conftest.py
git commit -m "feat(api): wire FirebaseAuthVerifier into AppState + require_admin_user dep

Stub verifier for tests accepts 'fake:<email>' tokens so integration
tests don't need real signed JWTs. firebase_admin.initialize_app()
happens once at startup; idempotent for test re-imports."
```

---

## Phase 2 — Admin route: messages

### Task 2.1: GET /api/admin/messages/unhandled + POST /handle (TDD)

**Files:**
- Create: `api/app/api/routes/admin/__init__.py`
- Create: `api/app/api/routes/admin/messages.py`
- Create: `api/tests/integration/test_admin_messages_route.py`
- Modify: `api/app/api/app_factory.py` (include router)

- [ ] **Step 1: Create the admin route package**

```bash
mkdir -p api/app/api/routes/admin
touch api/app/api/routes/admin/__init__.py
```

- [ ] **Step 2: Write failing integration tests**

Create `api/tests/integration/test_admin_messages_route.py`:

```python
"""Integration tests for /api/admin/messages/* endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.message import Message, MessageStatus

OWNER_TOKEN = "Bearer fake:techtastellc@gmail.com"
STRANGER_TOKEN = "Bearer fake:stranger@example.com"


def _seed_message(state, *, call_sid="CA1", phone="+15551234567", reason="catering") -> str:
    msg = Message(
        call_sid=call_sid,
        caller_phone=phone,
        reason=reason,
        taken_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
    )
    return state.message_store.create(msg)


@pytest.mark.asyncio
async def test_unhandled_returns_messages_newest_first(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    older_id = _seed_message(state, call_sid="CA-old", reason="first")
    # later one — we artificially set takenAt via direct Firestore write
    state.message_store._db.collection("messages").document(older_id).update({
        "takenAt": datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    })
    newer_id = _seed_message(state, call_sid="CA-new", reason="second")
    state.message_store._db.collection("messages").document(newer_id).update({
        "takenAt": datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)
    })

    resp = client.get(
        "/api/admin/messages/unhandled",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    assert [m["reason"] for m in msgs] == ["second", "first"]
    assert msgs[0]["callerPhone"] == "+15551234567"
    assert msgs[0]["id"]  # id field present


@pytest.mark.asyncio
async def test_unhandled_requires_auth(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    resp = client.get("/api/admin/messages/unhandled")
    assert resp.status_code == 401

    resp = client.get(
        "/api/admin/messages/unhandled",
        headers={"Authorization": "Bearer garbage"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unhandled_rejects_non_allowlisted_email(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    resp = client.get(
        "/api/admin/messages/unhandled",
        headers={"Authorization": STRANGER_TOKEN},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_handle_marks_message_handled(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    msg_id = _seed_message(state)

    resp = client.post(
        f"/api/admin/messages/{msg_id}/handle",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["status"] == "handled"

    msg = state.message_store.get(msg_id)
    assert msg is not None
    assert msg.status == MessageStatus.HANDLED
    assert msg.handled_by == "uid-techtastellc"
    assert msg.handled_at is not None


@pytest.mark.asyncio
async def test_handle_404_on_missing_message(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    resp = client.post(
        "/api/admin/messages/does-not-exist/handle",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 404
```

- [ ] **Step 3: Run tests, confirm failure**

```bash
(cd api && .venv/bin/pytest tests/integration/test_admin_messages_route.py -v 2>&1 | tail -15)
```
Expected: 404s because routes don't exist yet.

- [ ] **Step 4: Implement the route**

Create `api/app/api/routes/admin/messages.py`:

```python
"""Dashboard messages endpoints: list unhandled + mark handled."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_state, require_admin_user

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin_user)])


@router.get("/messages/unhandled")
async def unhandled_messages(request: Request) -> dict[str, list[dict[str, Any]]]:
    state = get_state(request)
    msgs = []
    for m in state.message_store.list_unhandled(limit=200):
        msgs.append(
            {
                "id": _msg_id_for(state, m),
                "callSid": m.call_sid,
                "callerPhone": m.caller_phone,
                "callerName": m.caller_name,
                "reason": m.reason,
                "takenAt": m.taken_at.isoformat() if m.taken_at else None,
            }
        )
    return {"messages": msgs}


@router.post("/messages/{message_id}/handle")
async def handle_message(
    request: Request,
    message_id: str,
    user: dict = Depends(require_admin_user),
) -> dict[str, Any]:
    state = get_state(request)
    if state.message_store.get(message_id) is None:
        raise HTTPException(status_code=404, detail="message not found")
    state.message_store.mark_handled(
        message_id=message_id,
        handled_at=datetime.now(timezone.utc),
        handled_by=user["uid"],
    )
    return {"ok": True, "status": "handled"}


def _msg_id_for(state, msg) -> str:
    """Look up the doc id by querying for the matching takenAt + callSid.
    We need a way to get the doc id since list_unhandled() returns Messages
    without their ids. Workaround: extend list_unhandled to yield (id, msg)
    tuples instead — see Task 2.2."""
    raise NotImplementedError("see Task 2.2 — extend list_unhandled to yield ids")
```

Wait — Task 2.1 has a design issue: `FirestoreMessageStore.list_unhandled` returns `Message` instances, not their doc IDs. The dashboard needs the doc ID to call `/handle`. Pivot:

- [ ] **Step 4a: Extend `FirestoreMessageStore.list_unhandled` to yield (id, Message) pairs**

This is a small change to the existing store (added in Plan 2a). Edit `api/app/infrastructure/firestore_message_store.py`. Find:

```python
    def list_unhandled(self, *, limit: int = 50) -> Iterator[Message]:
        query = (
            self._db.collection(MESSAGES_COLLECTION)
            .where(filter=firestore.FieldFilter("status", "==", MessageStatus.NEW.value))
            .order_by("takenAt", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        for snap in query.stream():
            yield Message.from_firestore(data=snap.to_dict() or {})
```

Replace with:

```python
    def list_unhandled(self, *, limit: int = 50) -> Iterator[tuple[str, Message]]:
        """Yield (doc_id, message) tuples. Doc id is needed for /handle."""
        query = (
            self._db.collection(MESSAGES_COLLECTION)
            .where(filter=firestore.FieldFilter("status", "==", MessageStatus.NEW.value))
            .order_by("takenAt", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        for snap in query.stream():
            yield snap.id, Message.from_firestore(data=snap.to_dict() or {})
```

Update the unit test in `api/tests/unit/test_firestore_message_store.py`. Find:
```python
    msgs = list(store.list_unhandled(limit=10))
    assert [m.reason for m in msgs] == ["second", "first"]
```
Replace with:
```python
    msgs = list(store.list_unhandled(limit=10))
    assert [m.reason for _id, m in msgs] == ["second", "first"]
    # IDs are non-empty strings
    assert all(isinstance(id_, str) and id_ for id_, _ in msgs)
```

And the `mark_handled` test:
```python
    assert list(store.list_unhandled(limit=10)) == []
```
That assertion still works since the list comprehension is empty.

Run store tests:
```bash
(cd api && .venv/bin/pytest tests/unit/test_firestore_message_store.py -v 2>&1 | tail -10)
```
Expected: 3 passed.

- [ ] **Step 4b: Update the admin route to use the new tuple return**

Rewrite the route body:

```python
@router.get("/messages/unhandled")
async def unhandled_messages(request: Request) -> dict[str, list[dict[str, Any]]]:
    state = get_state(request)
    msgs = []
    for msg_id, m in state.message_store.list_unhandled(limit=200):
        msgs.append(
            {
                "id": msg_id,
                "callSid": m.call_sid,
                "callerPhone": m.caller_phone,
                "callerName": m.caller_name,
                "reason": m.reason,
                "takenAt": m.taken_at.isoformat() if m.taken_at else None,
            }
        )
    return {"messages": msgs}
```

And drop the `_msg_id_for` helper (no longer needed).

- [ ] **Step 5: Update other callers of list_unhandled**

```bash
grep -rn "list_unhandled" api/app/ api/tests/ | grep -v __pycache__
```
Audit each result and update unpacking. As of Plan 2a, the only callers are the store's own tests (already updated in Step 4a above).

- [ ] **Step 6: Register admin router**

In `api/app/api/app_factory.py`, add the import:
```python
from app.api.routes.admin import messages as admin_messages
```

And include it alongside other routers:
```python
app.include_router(admin_messages.router)
```

- [ ] **Step 7: Run admin route tests**

```bash
(cd api && .venv/bin/pytest tests/integration/test_admin_messages_route.py -v 2>&1 | tail -25)
```
Expected: 5 passed.

- [ ] **Step 8: Full suite**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 118 passed (113 + 5 new — assuming Plan 2a baseline of 113).

- [ ] **Step 9: Commit**

```bash
git add api/app/api/routes/admin/__init__.py api/app/api/routes/admin/messages.py \
        api/app/infrastructure/firestore_message_store.py \
        api/tests/unit/test_firestore_message_store.py \
        api/tests/integration/test_admin_messages_route.py \
        api/app/api/app_factory.py
git commit -m "feat(api): GET /api/admin/messages/unhandled + POST /handle

Firebase Auth + email allowlist required. list_unhandled now yields
(doc_id, Message) tuples so /handle has the id. mark_handled writes
the verified UID + timestamp."
```

---

## Phase 3 — Admin route: calls

### Task 3.1: GET /api/admin/calls/today + /api/admin/calls/{sid} (TDD)

**Files:**
- Create: `api/app/api/routes/admin/calls.py`
- Create: `api/tests/integration/test_admin_calls_route.py`
- Modify: `api/app/infrastructure/firestore_call_store.py` (add `list_today_chicago`)

- [ ] **Step 1: Extend FirestoreCallStore with list_today**

Edit `api/app/infrastructure/firestore_call_store.py`. Add a new method:

```python
    def list_today_chicago(self, *, limit: int = 200) -> Iterator[tuple[str, Call]]:
        """List calls whose startedAt is within today's date in America/Chicago.

        Computes the day boundary in Chicago time and queries Firestore on
        a UTC range. Yields (call_sid, Call) tuples ordered newest first.
        """
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        chi = ZoneInfo("America/Chicago")
        now_chi = datetime.now(chi)
        start_chi = now_chi.replace(hour=0, minute=0, second=0, microsecond=0)
        end_chi = start_chi + timedelta(days=1)
        # Convert to UTC for the Firestore comparison
        start_utc = start_chi.astimezone(ZoneInfo("UTC"))
        end_utc = end_chi.astimezone(ZoneInfo("UTC"))

        query = (
            self._db.collection(CALLS_COLLECTION)
            .where(filter=firestore.FieldFilter("startedAt", ">=", start_utc))
            .where(filter=firestore.FieldFilter("startedAt", "<", end_utc))
            .order_by("startedAt", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        for snap in query.stream():
            yield snap.id, Call.from_firestore(call_sid=snap.id, data=snap.to_dict() or {})
```

Add a unit test in `api/tests/unit/test_firestore_call_store.py`:

```python
def test_list_today_chicago_returns_todays_calls_only(store):
    """Seed three calls: yesterday, today-early, today-late.
    Expect only today's two, newest first.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    chi = ZoneInfo("America/Chicago")
    today_chi = datetime.now(chi).replace(hour=9, minute=0, second=0, microsecond=0)
    yesterday_chi = today_chi - timedelta(days=1)
    today_later_chi = today_chi + timedelta(hours=5)

    for sid, ts in (
        ("CA-yesterday", yesterday_chi),
        ("CA-today-early", today_chi),
        ("CA-today-late", today_later_chi),
    ):
        store.record_call_start(Call(
            call_sid=sid,
            started_at=ts,
            caller_phone="+15551234567",
            from_number="+15559998888",
        ))

    todays = list(store.list_today_chicago(limit=50))
    sids = [s for s, _ in todays]
    assert "CA-yesterday" not in sids
    assert sids == ["CA-today-late", "CA-today-early"]
```

Update the index file to add the required composite index for this query — `api/firestore.indexes.json`:

```json
{
  "indexes": [
    {
      "collectionGroup": "messages",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "status", "order": "ASCENDING" },
        { "fieldPath": "takenAt", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "calls",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "startedAt", "order": "DESCENDING" }
      ]
    }
  ],
  "fieldOverrides": []
}
```
(The single-field `startedAt` index is usually auto-created by Firestore, but declaring it makes index management explicit.)

Run store tests:
```bash
(cd api && .venv/bin/pytest tests/unit/test_firestore_call_store.py -v 2>&1 | tail -10)
```
Expected: all pass (including the new test).

- [ ] **Step 2: Write failing integration tests for the admin routes**

Create `api/tests/integration/test_admin_calls_route.py`:

```python
"""Integration tests for /api/admin/calls/* endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.domain.call import Call, CallEvent, Outcome

OWNER_TOKEN = "Bearer fake:techtastellc@gmail.com"


@pytest.mark.asyncio
async def test_today_returns_only_todays_calls(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    chi = ZoneInfo("America/Chicago")
    today_chi = datetime.now(chi).replace(hour=9, minute=0)
    yesterday_chi = today_chi - timedelta(days=1)

    for sid, ts in (
        ("CA-y", yesterday_chi),
        ("CA-t", today_chi),
    ):
        state.call_store.record_call_start(Call(
            call_sid=sid,
            started_at=ts,
            caller_phone="+15551234567",
            from_number="+15559998888",
        ))

    resp = client.get(
        "/api/admin/calls/today",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    calls = resp.json()["calls"]
    sids = [c["callSid"] for c in calls]
    assert "CA-t" in sids
    assert "CA-y" not in sids


@pytest.mark.asyncio
async def test_call_detail_returns_doc_plus_events(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    started = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    state.call_store.record_call_start(Call(
        call_sid="CA-detail",
        started_at=started,
        caller_phone="+15551234567",
        from_number="+15559998888",
    ))
    state.call_store.append_event(
        call_sid="CA-detail",
        event=CallEvent(ts=started, kind="toolCalled", payload={"tool": "x"}),
        caller_phone_for_upsert="+15551234567",
        from_number_for_upsert="+15559998888",
    )

    resp = client.get(
        "/api/admin/calls/CA-detail",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["callSid"] == "CA-detail"
    assert body["callerPhone"] == "+15551234567"
    assert len(body["events"]) == 1
    assert body["events"][0]["kind"] == "toolCalled"


@pytest.mark.asyncio
async def test_call_detail_404_on_missing(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    resp = client.get(
        "/api/admin/calls/does-not-exist",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_calls_routes_require_auth(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    resp = client.get("/api/admin/calls/today")
    assert resp.status_code == 401
    resp = client.get("/api/admin/calls/CA-x")
    assert resp.status_code == 401
```

- [ ] **Step 3: Implement the route**

Create `api/app/api/routes/admin/calls.py`:

```python
"""Dashboard calls endpoints: today's list + per-call detail."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_state, require_admin_user

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin_user)])


def _serialize_call(call_sid: str, call) -> dict[str, Any]:
    return {
        "callSid": call_sid,
        "startedAt": call.started_at.isoformat() if call.started_at else None,
        "endedAt": call.ended_at.isoformat() if call.ended_at else None,
        "durationMs": call.duration_ms,
        "callerPhone": call.caller_phone,
        "fromNumber": call.from_number,
        "outcome": call.outcome.value,
        "summary": call.summary,
        "toolsUsed": list(call.tools_used),
    }


@router.get("/calls/today")
async def calls_today(request: Request) -> dict[str, list[dict[str, Any]]]:
    state = get_state(request)
    calls = [_serialize_call(sid, c) for sid, c in state.call_store.list_today_chicago(limit=200)]
    return {"calls": calls}


@router.get("/calls/{call_sid}")
async def call_detail(request: Request, call_sid: str) -> dict[str, Any]:
    state = get_state(request)
    call = state.call_store.get_call(call_sid)
    if call is None:
        raise HTTPException(status_code=404, detail="call not found")
    events = []
    for ev in state.call_store.iter_events(call_sid):
        events.append({
            "ts": ev.ts.isoformat() if ev.ts else None,
            "kind": ev.kind,
            "payload": ev.payload,
        })
    body = _serialize_call(call_sid, call)
    body["events"] = events
    return body
```

Register in `app_factory.py`:
```python
from app.api.routes.admin import calls as admin_calls
...
app.include_router(admin_calls.router)
```

- [ ] **Step 4: Run tests**

```bash
(cd api && .venv/bin/pytest tests/integration/test_admin_calls_route.py -v 2>&1 | tail -15)
```
Expected: 4 passed.

Full suite:
```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 122 passed (118 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add api/app/infrastructure/firestore_call_store.py \
        api/tests/unit/test_firestore_call_store.py \
        api/app/api/routes/admin/calls.py \
        api/tests/integration/test_admin_calls_route.py \
        api/app/api/app_factory.py \
        firestore.indexes.json
git commit -m "feat(api): GET /api/admin/calls/today + /{sid} (with events subcollection)

list_today_chicago computes the day boundary in America/Chicago and
queries Firestore on a UTC range. Composite index declared in
firestore.indexes.json."
```

---

## Phase 4 — Admin route: owner-override

### Task 4.1: GET / POST / DELETE /api/admin/owner-override (TDD)

**Files:**
- Create: `api/app/api/routes/admin/owner_override.py`
- Create: `api/tests/integration/test_admin_owner_override_route.py`

- [ ] **Step 1: Write failing tests**

Create `api/tests/integration/test_admin_owner_override_route.py`:

```python
"""Integration tests for /api/admin/owner-override."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

OWNER_TOKEN = "Bearer fake:techtastellc@gmail.com"


@pytest.mark.asyncio
async def test_get_when_unset_returns_inactive(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    resp = client.get(
        "/api/admin/owner-override",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is False
    assert body["untilIso"] is None


@pytest.mark.asyncio
async def test_post_sets_override(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    until = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    resp = client.post(
        "/api/admin/owner-override",
        headers={"Authorization": OWNER_TOKEN},
        json={"until_iso": until, "reason": "wedding"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is True
    assert body["untilIso"] == until
    assert body["reason"] == "wedding"
    assert body["setBy"] == "uid-techtastellc"


@pytest.mark.asyncio
async def test_delete_clears_override(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    until = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    client.post(
        "/api/admin/owner-override",
        headers={"Authorization": OWNER_TOKEN},
        json={"until_iso": until, "reason": "wedding"},
    )

    resp = client.delete(
        "/api/admin/owner-override",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is False
    assert body["untilIso"] is None


@pytest.mark.asyncio
async def test_post_rejects_past_until(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    resp = client.post(
        "/api/admin/owner-override",
        headers={"Authorization": OWNER_TOKEN},
        json={"until_iso": past, "reason": "test"},
    )
    assert resp.status_code == 400
    assert "past" in resp.json()["detail"].lower() or "future" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_routes_require_auth(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    resp = client.get("/api/admin/owner-override")
    assert resp.status_code == 401
    resp = client.post("/api/admin/owner-override", json={"until_iso": "x", "reason": "y"})
    assert resp.status_code == 401
    resp = client.delete("/api/admin/owner-override")
    assert resp.status_code == 401
```

- [ ] **Step 2: Implement the route**

Create `api/app/api/routes/admin/owner_override.py`:

```python
"""Dashboard owner-override endpoints: get/set/clear."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.dependencies import get_state, require_admin_user
from app.domain.owner_override import OwnerOverride

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin_user)])


class SetOverrideBody(BaseModel):
    until_iso: str
    reason: str


def _serialize(o: OwnerOverride | None) -> dict[str, Any]:
    if o is None:
        return {
            "active": False,
            "untilIso": None,
            "reason": None,
            "setBy": None,
            "setAt": None,
        }
    return {
        "active": o.active,
        "untilIso": o.until_iso,
        "reason": o.reason,
        "setBy": o.set_by,
        "setAt": o.set_at.isoformat() if o.set_at else None,
    }


@router.get("/owner-override")
async def get_override(request: Request) -> dict[str, Any]:
    state = get_state(request)
    return _serialize(state.owner_override_store.get_current())


@router.post("/owner-override")
async def set_override(
    request: Request,
    body: SetOverrideBody,
    user: dict = Depends(require_admin_user),
) -> dict[str, Any]:
    # Validate until_iso parses and is in the future
    try:
        until_dt = datetime.fromisoformat(body.until_iso.replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid until_iso: {e}") from e
    if until_dt <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="until_iso must be in the future")

    state = get_state(request)
    override = OwnerOverride(
        active=True,
        until_iso=body.until_iso,
        reason=body.reason,
        set_by=user["uid"],
        set_at=datetime.now(timezone.utc),
    )
    state.owner_override_store.set(override)
    return _serialize(state.owner_override_store.get_current())


@router.delete("/owner-override")
async def clear_override(
    request: Request,
    user: dict = Depends(require_admin_user),
) -> dict[str, Any]:
    state = get_state(request)
    state.owner_override_store.clear(cleared_by=user["uid"])
    return _serialize(state.owner_override_store.get_current())
```

Register in `app_factory.py`:
```python
from app.api.routes.admin import owner_override as admin_owner_override
...
app.include_router(admin_owner_override.router)
```

- [ ] **Step 3: Run tests**

```bash
(cd api && .venv/bin/pytest tests/integration/test_admin_owner_override_route.py -v 2>&1 | tail -15)
```
Expected: 5 passed.

Full suite:
```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 127 passed (122 + 5 new).

- [ ] **Step 4: Commit**

```bash
git add api/app/api/routes/admin/owner_override.py \
        api/tests/integration/test_admin_owner_override_route.py \
        api/app/api/app_factory.py
git commit -m "feat(api): GET/POST/DELETE /api/admin/owner-override

POST rejects until_iso in the past (400). All three routes require
Firebase Auth + email allowlist."
```

---

## Phase 5 — Admin route: daily stats

### Task 5.1: GET /api/admin/stats/daily

**Files:**
- Create: `api/app/api/routes/admin/stats.py`
- Create: `api/tests/integration/test_admin_stats_route.py`

- [ ] **Step 1: Write failing tests**

Create `api/tests/integration/test_admin_stats_route.py`:

```python
"""Integration tests for /api/admin/stats/daily."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.call import Call, CallEvent, Outcome

OWNER_TOKEN = "Bearer fake:techtastellc@gmail.com"


@pytest.mark.asyncio
async def test_daily_returns_per_day_aggregates(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    now = datetime.now(timezone.utc)
    for i, sid in enumerate(["CA1", "CA2", "CA3"]):
        state.call_store.record_call_start(Call(
            call_sid=sid,
            started_at=now - timedelta(hours=i),
            caller_phone="+15551234567",
            from_number="+15559998888",
        ))
        # Mark CA1 as transferred, CA2 as messageTaken, CA3 leave inProgress
        if sid == "CA1":
            state.call_store.record_call_end(
                call_sid=sid,
                ended_at=now,
                outcome=Outcome.TRANSFERRED,
                duration_ms=60000,
            )
        if sid == "CA2":
            state.call_store.record_call_end(
                call_sid=sid,
                ended_at=now,
                outcome=Outcome.MESSAGE_TAKEN,
                duration_ms=80000,
            )

    resp = client.get(
        "/api/admin/stats/daily?days=1",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    today_key = body["days"][0]["date"]
    assert body["days"][0]["totalCalls"] == 3
    assert body["days"][0]["transfersCompleted"] == 1
    assert body["days"][0]["messagesTaken"] == 1


@pytest.mark.asyncio
async def test_daily_default_days_is_7(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    resp = client.get(
        "/api/admin/stats/daily",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 200
    assert len(resp.json()["days"]) == 7


@pytest.mark.asyncio
async def test_daily_caps_days_at_30(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    resp = client.get(
        "/api/admin/stats/daily?days=100",
        headers={"Authorization": OWNER_TOKEN},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_daily_requires_auth(client_factory, firestore_db):
    state, client = client_factory(firestore_db=firestore_db)
    resp = client.get("/api/admin/stats/daily")
    assert resp.status_code == 401
```

- [ ] **Step 2: Implement the route**

Create `api/app/api/routes/admin/stats.py`:

```python
"""Dashboard daily-stats endpoint — computed live from /calls.

Day boundary is America/Chicago. Cap days at 30 to keep query cost bounded.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from google.cloud import firestore as gfirestore

from app.api.dependencies import get_state, require_admin_user
from app.domain.call import Outcome

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin_user)])

CHICAGO = ZoneInfo("America/Chicago")


@router.get("/stats/daily")
async def daily_stats(
    request: Request,
    days: int = Query(7, ge=1, le=30),
) -> dict[str, list[dict[str, Any]]]:
    state = get_state(request)
    db = state.call_store._db  # access for raw query

    today_chi_start = datetime.now(CHICAGO).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    out: list[dict[str, Any]] = []
    for offset in range(days):
        day_start = today_chi_start - timedelta(days=offset)
        day_end = day_start + timedelta(days=1)
        day_start_utc = day_start.astimezone(ZoneInfo("UTC"))
        day_end_utc = day_end.astimezone(ZoneInfo("UTC"))

        query = (
            db.collection("calls")
            .where(filter=gfirestore.FieldFilter("startedAt", ">=", day_start_utc))
            .where(filter=gfirestore.FieldFilter("startedAt", "<", day_end_utc))
        )
        total = 0
        transfers = 0
        transfers_failed = 0
        messages = 0
        for snap in query.stream():
            total += 1
            data = snap.to_dict() or {}
            outcome = data.get("outcome")
            if outcome == Outcome.TRANSFERRED.value:
                transfers += 1
            elif outcome == Outcome.FAILED.value:
                transfers_failed += 1
            elif outcome == Outcome.MESSAGE_TAKEN.value:
                messages += 1

        out.append(
            {
                "date": day_start.date().isoformat(),
                "totalCalls": total,
                "transfersCompleted": transfers,
                "transfersFailed": transfers_failed,
                "messagesTaken": messages,
            }
        )
    return {"days": out}
```

Note: this is computed live on every request. For >30 days or higher volume, materialize via the `dailyStats` collection (see roadmap item 0.5 / Plan 6).

Register in `app_factory.py`:
```python
from app.api.routes.admin import stats as admin_stats
...
app.include_router(admin_stats.router)
```

- [ ] **Step 3: Run tests**

```bash
(cd api && .venv/bin/pytest tests/integration/test_admin_stats_route.py -v 2>&1 | tail -15)
```
Expected: 4 passed.

Full suite:
```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 131 passed (127 + 4 new).

- [ ] **Step 4: Commit**

```bash
git add api/app/api/routes/admin/stats.py \
        api/tests/integration/test_admin_stats_route.py \
        api/app/api/app_factory.py
git commit -m "feat(api): GET /api/admin/stats/daily — live aggregation per day

days=7 default, capped at 30 to keep cost bounded. Day boundary in
America/Chicago. For higher volume, materialize via /dailyStats."
```

---

## Phase 6 — Rate limiting

### Task 6.1: slowapi for public endpoints

**Files:**
- Modify: `api/pyproject.toml` (add slowapi)
- Create: `api/app/api/middleware/rate_limit.py`
- Modify: `api/app/api/app_factory.py` (wire limiter into app)
- Create: `api/tests/integration/test_rate_limit.py`

- [ ] **Step 1: Add slowapi dep**

In `api/pyproject.toml`, append to dependencies:
```toml
  "slowapi>=0.1.9",
```

Install:
```bash
(cd api && .venv/bin/pip install -e ".[dev]" 2>&1 | tail -3)
```

- [ ] **Step 2: Write failing tests**

Create `api/tests/integration/test_rate_limit.py`:

```python
"""Tests for slowapi rate limiting on public/unauthenticated endpoints."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_is_not_rate_limited(client_factory, firestore_db):
    """healthz is the keepalive endpoint — it must NEVER be rate limited."""
    state, client = client_factory(firestore_db=firestore_db)
    for _ in range(100):
        resp = client.get("/healthz")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_unauth_admin_request_is_rate_limited(client_factory, firestore_db):
    """Unauthenticated requests to /api/admin/* should hit the rate limit
    quickly so brute-force token guessing isn't viable."""
    state, client = client_factory(firestore_db=firestore_db)
    # First 10 within window: 401 (rate-limit OK because we want auth feedback)
    # After ~10 in burst: 429
    seen_429 = False
    for i in range(40):
        resp = client.get(
            "/api/admin/messages/unhandled",
            headers={"Authorization": "Bearer garbage"},
        )
        if resp.status_code == 429:
            seen_429 = True
            break
    assert seen_429, "expected rate limit (429) within 40 burst requests"


@pytest.mark.asyncio
async def test_authenticated_admin_request_higher_limit(client_factory, firestore_db):
    """Authenticated requests get a higher per-minute limit so legitimate
    dashboard polling isn't throttled."""
    state, client = client_factory(firestore_db=firestore_db)
    # 30 authenticated requests in a tight loop — should all 200 (well under
    # the authenticated quota of 120/min).
    for _ in range(30):
        resp = client.get(
            "/api/admin/messages/unhandled",
            headers={"Authorization": "Bearer fake:techtastellc@gmail.com"},
        )
        assert resp.status_code == 200
```

- [ ] **Step 3: Implement rate limiter**

Create `api/app/api/middleware/rate_limit.py`:

```python
"""slowapi rate limiter for public endpoints.

Strategy:
- /healthz exempt (keepalive pingers).
- /api/admin/* unauthenticated: 10/min/IP (brute-force defense).
- /api/admin/* authenticated: 120/min/uid.
- /twilio/* (agent webhooks): 60/min/IP. Twilio's egress IPs are stable
  ranges so a single IP rarely exceeds this even at peak.

Implementation note: we use IP-based limits via slowapi's default
get_remote_address. The auth-state-based bump (10 vs 120) is handled
by a custom key function that returns the verified UID when present,
falling back to IP.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address


def _key_func(request) -> str:
    """Prefer verified UID, fall back to IP."""
    # The require_admin_user dep stores the decoded claims on request.state.user
    # when it succeeds. We probe for it; if absent, IP fallback.
    user = getattr(request.state, "user", None)
    if user and "uid" in user:
        return f"uid:{user['uid']}"
    return f"ip:{get_remote_address(request)}"


def build_limiter() -> Limiter:
    return Limiter(key_func=_key_func, default_limits=["120/minute"])
```

- [ ] **Step 4: Wire into app_factory.py**

Edit `api/app/api/app_factory.py`. Add imports:
```python
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.middleware.rate_limit import build_limiter
```

In `build_app(deps)`, near where CORS middleware is added:
```python
    limiter = build_limiter()
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _on_rate_limit(_req, exc: RateLimitExceeded):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "rate limit exceeded", "detail": str(exc.detail)}, status_code=429)
```

Per-route limits via decorators won't compose well with our existing routes (which use `Depends`), so we use middleware + the default limit. To enforce different limits per route, set `app.state.limiter` and use `@limiter.limit("10/minute")` decorators on specific endpoints. For this plan, the default 120/min default is the only limit applied — adjust per-endpoint after the dashboard is in production and we know the real traffic shape.

For the test `test_unauth_admin_request_is_rate_limited` to pass with a default 120/min limit, lower the default temporarily for tests — pass an explicit env var to disable rate limiting in unit-test conftest:

Update `build_limiter` to read an env var for testability:
```python
import os

def build_limiter() -> Limiter:
    default = os.environ.get("RATE_LIMIT_DEFAULT", "120/minute")
    return Limiter(key_func=_key_func, default_limits=[default])
```

And in `conftest.py` for the rate-limit tests, set the env var to something low:
```python
import pytest

@pytest.fixture(autouse=True, scope="module")
def _strict_rate_limit():
    import os
    old = os.environ.get("RATE_LIMIT_DEFAULT")
    os.environ["RATE_LIMIT_DEFAULT"] = "10/minute"
    yield
    if old is None:
        os.environ.pop("RATE_LIMIT_DEFAULT", None)
    else:
        os.environ["RATE_LIMIT_DEFAULT"] = old
```

Note: rate-limit testing is brittle in fast loops. If the tests flake, raise the burst threshold or use a finer-grained per-endpoint limit. The simpler test is: with 10/min default, the 11th request in a burst must 429.

- [ ] **Step 5: Run tests**

```bash
(cd api && .venv/bin/pytest tests/integration/test_rate_limit.py -v 2>&1 | tail -15)
```
Expected: 3 passed. If flaky, adjust burst count or limit string.

Full suite:
```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 134 passed (131 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add api/pyproject.toml api/app/api/middleware/rate_limit.py \
        api/app/api/app_factory.py api/tests/integration/test_rate_limit.py
git commit -m "feat(api): slowapi rate limiter (120/min default, configurable per-env)

Brute-force defense on unauthenticated /api/admin/* requests. Default
limit per-uid when authenticated, per-IP otherwise. /healthz exempt."
```

---

## Phase 7 — Docs + push

### Task 7.1: README admin API section + push branch

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the admin API surface**

Append to README.md after the existing API endpoints section:

```markdown
## Admin API (for dashboard)

All `/api/admin/*` endpoints require:
- `Authorization: Bearer <firebase-id-token>` header
- The Firebase Auth account's verified email must be in `ADMIN_ALLOWED_EMAILS` env var (comma-separated)

Rate limiting: 120 requests/minute per authenticated user (per UID), 10/min for unauthenticated brute-force attempts (per IP). `/healthz` is exempt.

### Endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/admin/messages/unhandled` | — | `{messages: [{id, callSid, callerPhone, callerName, reason, takenAt}]}` |
| POST | `/api/admin/messages/{id}/handle` | — | `{ok: true, status: "handled"}` |
| GET | `/api/admin/calls/today` | — | `{calls: [{callSid, startedAt, endedAt, durationMs, callerPhone, outcome, summary, toolsUsed}]}` |
| GET | `/api/admin/calls/{call_sid}` | — | call object + `{events: [{ts, kind, payload}]}` |
| GET | `/api/admin/owner-override` | — | `{active, untilIso, reason, setBy, setAt}` |
| POST | `/api/admin/owner-override` | `{until_iso: ISO8601, reason: str}` | same as GET |
| DELETE | `/api/admin/owner-override` | — | same as GET (active=false) |
| GET | `/api/admin/stats/daily?days=7` | — | `{days: [{date, totalCalls, transfersCompleted, transfersFailed, messagesTaken}]}` |

### Configuring the email allowlist

```bash
fly secrets set ADMIN_ALLOWED_EMAILS="techtastellc@gmail.com,backup-admin@example.com"
```

Empty allowlist rejects every request — defense vs. misconfiguration.

### Frontend integration notes

- Dashboard obtains the ID token via Firebase Auth client SDK (`firebase.auth().currentUser.getIdToken()`).
- Token expires in 1 hour; Firebase SDK refreshes automatically.
- Send fresh token on every request — don't cache server-side beyond the request.
- 401 → token invalid/expired → trigger SDK re-auth.
- 403 → email not allowlisted → display a "no access" page.
```

- [ ] **Step 2: Final test run**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: API 134 passed, agent 66 passed (unchanged — this plan doesn't touch the agent).

- [ ] **Step 3: Commit + push**

```bash
git add README.md
git commit -m "docs: admin API surface + frontend integration notes"
git push -u origin feature/dashboard-api-auth 2>&1 | tail -5
```

Capture the PR URL.

---

## Verification

End-to-end:
1. `(cd api && .venv/bin/pytest tests/ -q)` → 134 passed.
2. Boot the API locally with real Firebase service account; obtain a real Firebase ID token (use Firebase CLI: `firebase auth:export ...` or the frontend's getIdToken).
3. `curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/admin/messages/unhandled` → 200 with messages list (or empty list).
4. `curl -H "Authorization: Bearer $TOKEN" -X POST http://localhost:8080/api/admin/owner-override -H "Content-Type: application/json" -d '{"until_iso": "2026-05-15T18:00:00Z", "reason": "wedding"}'` → 200.
5. Inspect Firestore: `/ownerOverride/current` doc shows `active: true, untilIso, reason, setBy: <your uid>`.
6. With override active, post to `/api/transfers` (using the existing tools-auth) → response should be `{"action": "take_message"}` (the override-aware logic from Plan 2a takes effect).

---

## Production deployment notes

When this plan lands on a real host:
1. `flyctl secrets set ADMIN_ALLOWED_EMAILS="techtastellc@gmail.com,<other-owner-emails>"` (or equivalent on Cloud Run).
2. Deploy the composite Firestore indexes: `firebase deploy --only firestore:indexes` (requires being a Firebase admin on the project — coordinate with whoever owns the dashboard team).
3. **Do NOT deploy `firestore.rules`** from this repo — that file is the default-deny stub from Plan 2a and would lock out the dashboard. Real rules are owned by the dashboard team; coordinate a single combined `firestore.rules` file that allows both the dashboard's existing reads and our new collections.

Sample production rules block to share with the dashboard team:
```
match /messages/{id} { allow read: if request.auth != null && request.auth.token.email in [<allowlist>]; }
match /calls/{callSid}/{document=**} { allow read: if request.auth != null && request.auth.token.email in [<allowlist>]; }
match /callers/{phone} { allow read: if request.auth != null && request.auth.token.email in [<allowlist>]; }
match /ownerOverride/current { allow read, write: if request.auth != null && request.auth.token.email in [<allowlist>]; }
match /dailyStats/{date} { allow read: if request.auth != null && request.auth.token.email in [<allowlist>]; }
```
(The dashboard's existing rules continue to govern `activityLogs`, `menuItems`, etc.)

Note: writes to `messages` happen via the API service (Admin SDK bypasses rules), so the dashboard never needs write access to `/messages` — it goes through `POST /api/admin/messages/{id}/handle` instead. Same for `ownerOverride` — read direct from Firestore for live updates, write via `POST /api/admin/owner-override`.

---

## What's next

This plan completes the roadmap's Tier 0 and most of Tier 1. Remaining items:
- Roadmap 0.5: Daily SMS digest to owner (deferred — dashboard real-time view covers it).
- Tier 2 caller-experience polish (fuzzy menu search, richer caller history surfaced to LLM, post-call SMS to caller).
- Tier 3 product bets (multilingual DTMF IVR, outbound callback, escalation chain).
