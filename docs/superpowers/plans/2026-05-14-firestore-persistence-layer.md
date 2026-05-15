# Firestore Persistence Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the API service's local JSONL persistence (`api/data/events.jsonl`) with Cloud Firestore, writing to new top-level collections (`calls`, `callers`, `messages`, `ownerOverride`, `dailyStats`) alongside the existing dashboard collections (`activityLogs`, `menuItems`, etc.) in project `spicy-desi-chicago`.

**Architecture:** A new `FirestoreClient` infrastructure module handles credential loading (ambient first, service-account-JSON fallback). Four `Firestore*Store` classes provide typed reads/writes scoped to a single collection each. Existing routes (`/api/messages`, `/api/calls/{sid}/event`, `/api/callers/history`, `/api/transfers`) rewire to call these stores instead of `JsonlEventLog`. Pydantic models in `api/app/domain/` use snake_case Python; the stores convert to camelCase Firestore field names on write and back on read. Tests run against a Firestore emulator (`firebase emulators:start --only firestore`) started per test session — hermetic, no internet.

**Tech Stack:** Python 3.12, FastAPI, `firebase-admin` (for Auth ID token verification — used later in Plan 4), `google-cloud-firestore`, Firebase Emulator Suite (`firebase-tools` CLI), `pytest`.

**Branch:** `feature/firestore-persistence` (created from `feature/fly-deploy-and-security` so deploy work is preserved). At end of plan, branch is rebasable onto main once deploy lands.

**Out of scope (separate plans):**
- Agent's adoption of call-lifecycle routes (`/calls/{sid}/start`, `/end`, `/summary`) — Plan 2b
- End-of-call LLM summary generation — Plan 2b
- Dashboard auth (Firebase ID tokens for browser → API) — Plan 4
- Migration of `pickup_state.json` to Firestore — Plan 5 (low-priority)
- Migration of agent's menu source from Square to Firestore — out of scope per design decision
- **Deploying `firestore.rules` to production** — the rules file in this plan is for the LOCAL EMULATOR only. Production rules are governed by the existing dashboard team and must not be modified by this plan (deploying our default-deny rules would lock out the dashboard's reads). Real rules coordination is a Plan 4 task.

---

## ⚠️ Data-safety guarantees

The existing Firestore project has 8 collections that the dashboard owns: `activityLogs`, `checklistTemplates`, `inventoryLogs`, `items`, `menuCategories`, `menuItems`, `stores`, `users`. **This plan must not read from, write to, or delete any of them.** Three concrete guarantees:

1. **Collection-name allowlist enforced in code.** Every store (Call, Caller, Message, OwnerOverride) declares its collection as a module-level constant and uses it as the only collection reference. Stores are physically incapable of writing to a different collection because the name is never parameterized. Reviewed in Tasks 4.1–4.4.

2. **Backfill script is restricted to OUR collections.** The `--clear` flag in `backfill_jsonl_to_firestore.py` operates on a hardcoded list: `("calls", "callers", "messages")`. It cannot touch dashboard collections by mistake. See Task 6.1 Step 2 for the explicit list. The script also refuses to run if its target collections happen to contain unexpected dashboard fields (sanity-check added in Task 6.1).

3. **Pre-flight verification before the first production touch.** Task 0.5 explicitly inspects the production Firestore to confirm that our new collections (`calls`, `callers`, `messages`, `ownerOverride`, `dailyStats`) don't yet exist — i.e., we won't be merging with anyone else's writes — and that the existing 8 collections are present and reachable (proves our credentials are read-only-correct for them).

Additional protection: `firestore.rules` in this plan is **default-deny everywhere** AND has a banner comment instructing the engineer NOT to deploy it. Tests against the emulator use `firebase-admin` which bypasses rules; production reads from this code use the Admin SDK which also bypasses rules. Rules deployment is a Plan 4 concern handled in coordination with the dashboard team.

---

## Pre-flight context

- Branch state: `feature/fly-deploy-and-security` has 18 commits ahead of main. We branch from there.
- Firestore project: `spicy-desi-chicago`
- Service account JSON: `/Users/milindp/Downloads/spicy-desi-chicago-firebase-adminsdk-7osff-dc6b3e51bc.json` (will be moved to `~/.config/spicy-desi/firebase-admin.json` in Task 1.4)
- Existing collections (UNTOUCHED): `activityLogs`, `checklistTemplates`, `inventoryLogs`, `items`, `menuCategories`, `menuItems`, `stores`, `users`
- Firebase Auth UID of owner: `Woavythv26dZ7XlJngL7lKakQ7N2` (email `techtastellc@gmail.com`)
- Existing tests: 75 in API venv, 66 in agent venv — must all keep passing.

---

## Firestore schema (this plan creates these collections)

```
/calls/{callSid}                          ← doc id = Twilio CallSid
  startedAt        Timestamp
  endedAt          Timestamp | null
  durationMs       int | null
  callerPhone      string  (E.164, e.g. "+15551234567")
  fromNumber       string  (Twilio number called)
  outcome          "inProgress" | "resolved" | "transferred" | "messageTaken" | "failed"
  summary          string | null         (filled by Plan 2b)
  toolsUsed        array<string>         (e.g. ["listMenuCategories", "sendOrderLink"])
  /events/{autoId}                       ← subcollection
    ts             Timestamp
    kind           string                (e.g. "toolCalled", "transferInitiated")
    payload        map

/callers/{e164}                           ← doc id = phone in E.164 with leading "+"
  firstSeen        Timestamp
  lastSeen         Timestamp
  callCount        int
  lastCallSid      string | null
  lastOutcome      string | null
  notes            string

/messages/{autoId}                        ← doc id = Firestore-generated
  callSid          string
  callerPhone      string  (E.164)
  callerName       string | null
  reason           string
  takenAt          Timestamp
  status           "new" | "handled"
  handledAt        Timestamp | null
  handledBy        string | null         (Firebase Auth UID)

/ownerOverride/current                    ← singleton doc, fixed id "current"
  active           bool
  untilIso         string | null         (ISO 8601 with timezone)
  reason           string | null
  setBy            string                (Firebase Auth UID)
  setAt            Timestamp

/dailyStats/{yyyy-mm-dd}                  ← doc id = date in America/Chicago, e.g. "2026-05-14"
  totalCalls           int
  transfersCompleted   int
  transfersFailed      int
  messagesTaken        int
  computedAt           Timestamp
```

**Naming convention:** Firestore fields are **camelCase** to match your existing dashboard collections. Python code is **snake_case** as the rest of the codebase. Stores translate at the boundary.

---

## File structure (new files in this plan)

```
api/
  app/
    domain/
      call.py                ← Call, CallEvent, Outcome enum  (Pydantic)
      caller.py              ← Caller
      message.py             ← Message (also stays compatible with existing MessageRequest)
      owner_override.py      ← OwnerOverride
    infrastructure/
      firestore_client.py    ← client init: ambient creds or JSON path
      firestore_call_store.py
      firestore_caller_store.py
      firestore_message_store.py
      firestore_owner_override_store.py
  scripts/
    backfill_jsonl_to_firestore.py
  tests/
    helpers/
      firestore_emulator.py  ← starts/stops emulator, clears between tests
    unit/
      test_firestore_call_store.py
      test_firestore_caller_store.py
      test_firestore_message_store.py
      test_firestore_owner_override_store.py
    integration/
      test_calls_route_firestore.py    ← replaces parts of test_events_route + test_messages_route

firebase.json                  ← emulator config at repo root
.firebaserc                    ← project alias config

agent/                         ← UNCHANGED in this plan
```

**Files modified:**
- `api/pyproject.toml` — add `firebase-admin`, `google-cloud-firestore`
- `api/app/infrastructure/config.py` — `FIREBASE_SERVICE_ACCOUNT_PATH` field
- `api/app/api/dependencies.py` — `AppState` gains the four stores; drops `event_log`
- `api/app/main.py` — wire stores into `AppState`
- `api/app/api/routes/events.py` — writes to `FirestoreCallStore.append_event`
- `api/app/api/routes/messages.py` — writes to `FirestoreMessageStore.create`
- `api/app/api/routes/callers.py` — reads from `FirestoreCallerStore.get`
- `api/app/services/transfer_decision_service.py` — consults `FirestoreOwnerOverrideStore.get_current` before weekly schedule
- `api/Dockerfile` — accepts service account via env (mounted as secret on Fly later)
- `docker-compose.yml` — passes service-account path + mounts it read-only
- `.env.example` — adds `FIREBASE_SERVICE_ACCOUNT_PATH`
- `.gitignore` — adds `firebase-debug.log`, `firestore-debug.log`, `firebase-export-*`
- `README.md` — Firestore setup + emulator quickstart

**Files deleted at end of plan:**
- `api/app/infrastructure/event_log.py` (replaced)
- `api/tests/unit/test_event_log.py` (replaced)
- `api/data/events.jsonl` (after one-time backfill — kept locally as backup, gitignored)

---

## Phase 0 — Pre-flight

### Task 0.1: Create the branch

**Files:** None.

- [ ] **Step 1: Branch from `feature/fly-deploy-and-security`**

```bash
git checkout feature/fly-deploy-and-security
git pull origin feature/fly-deploy-and-security
git checkout -b feature/firestore-persistence
```

- [ ] **Step 2: Confirm baseline**

```bash
git log --oneline -5
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 75 + 66 = 141 passing tests on the prior branch's tip.

### Task 0.2: Install `firebase-tools` for the emulator

**Files:** None (local-machine setup).

- [ ] **Step 1: Install via brew**

```bash
brew install firebase-cli
```
(If already installed, brew prints "already installed".)

- [ ] **Step 2: Verify**

```bash
firebase --version
```
Expected: prints `14.x.x` or higher.

- [ ] **Step 3: Start the emulator once to download the Java JAR (one-time download, ~50MB)**

```bash
firebase emulators:start --only firestore --project demo-test &
EMULATOR_PID=$!
sleep 10
kill $EMULATOR_PID
```
Expected: emulator started successfully and was killed. The first run downloads Firestore + Java JAR; subsequent runs are instant. The `demo-test` project alias is special — Firebase Emulator Suite treats any project starting with `demo-` as a fake project that never touches real Firebase. We use it for tests.

If Java isn't installed: `brew install openjdk@17`. Emulator needs JDK 11+.

### Task 0.3: Move the service-account JSON to a stable location

**Files:** `~/.config/spicy-desi/firebase-admin.json`

- [ ] **Step 1: Create destination dir + move file**

```bash
mkdir -p ~/.config/spicy-desi
mv /Users/milindp/Downloads/spicy-desi-chicago-firebase-adminsdk-7osff-dc6b3e51bc.json \
   ~/.config/spicy-desi/firebase-admin.json
chmod 600 ~/.config/spicy-desi/firebase-admin.json
```

- [ ] **Step 2: Verify it's still readable and project_id is intact**

```bash
python3 -c "import json; d=json.load(open('$HOME/.config/spicy-desi/firebase-admin.json')); print('project_id:', d['project_id'])"
```
Expected: `project_id: spicy-desi-chicago`.

- [ ] **Step 3: Note the new path for later steps**

You'll reference this path as `~/.config/spicy-desi/firebase-admin.json` throughout. The path goes into env via `FIREBASE_SERVICE_ACCOUNT_PATH`.

### Task 0.5: Pre-flight verification — confirm production Firestore is in a safe initial state

**Files:** None (read-only inspection of real Firestore).

This task runs ONCE before any code lands. It confirms that the 5 collections we're about to introduce (`calls`, `callers`, `messages`, `ownerOverride`, `dailyStats`) don't already exist in production, and that the 8 dashboard collections we must NOT touch are present and reachable with the credentials we have. If our new collections already have data, STOP — that's a sign someone else already wrote to those paths, and proceeding could merge incompatible schemas.

- [ ] **Step 1: Create a temporary inspection script**

```bash
cat > /tmp/preflight_firestore.py <<'EOF'
"""Pre-flight check: production Firestore state before Plan 2a execution."""
from __future__ import annotations

import os
import sys

from google.cloud import firestore
from google.oauth2 import service_account

OUR_NEW_COLLECTIONS = {"calls", "callers", "messages", "ownerOverride", "dailyStats"}
DASHBOARD_COLLECTIONS = {
    "activityLogs",
    "checklistTemplates",
    "inventoryLogs",
    "items",
    "menuCategories",
    "menuItems",
    "stores",
    "users",
}

sa_path = os.environ["FIREBASE_SERVICE_ACCOUNT_PATH"]
creds = service_account.Credentials.from_service_account_file(sa_path)
client = firestore.Client(project="spicy-desi-chicago", credentials=creds)

actual = {c.id for c in client.collections()}

print("=" * 70)
print("PRODUCTION FIRESTORE PRE-FLIGHT CHECK")
print("=" * 70)
print(f"\nFound {len(actual)} top-level collections: {sorted(actual)}\n")

# 1. Dashboard collections must be present (proves credentials work for them)
missing_dashboard = DASHBOARD_COLLECTIONS - actual
if missing_dashboard:
    print(f"⚠ WARNING: expected dashboard collections missing: {sorted(missing_dashboard)}")
    print("  (Maybe schema changed since this plan was written; verify with the dashboard owner.)")
else:
    print("✓ All 8 dashboard collections present.")

# 2. Our new collections MUST NOT exist yet
unexpected = OUR_NEW_COLLECTIONS & actual
if unexpected:
    print(f"\n❌ STOP: our new collections already exist: {sorted(unexpected)}")
    print("  This plan assumes a greenfield namespace. Aborting.")
    sys.exit(1)
print("\n✓ Our 5 new collections do not yet exist — safe to proceed.")

# 3. Confirm read access on a sample dashboard doc (proves SA is correctly scoped)
try:
    sample = next(iter(client.collection("users").limit(1).stream()), None)
    if sample is not None:
        print(f"✓ Read access on /users works (sample doc id: {sample.id[:8]}...).")
    else:
        print("⚠ /users collection is empty (unexpected but not blocking).")
except Exception as e:
    print(f"❌ Cannot read /users: {e}")
    sys.exit(1)

print("\n" + "=" * 70)
print("PRE-FLIGHT PASSED — safe to proceed with Plan 2a.")
print("=" * 70)
EOF
```

- [ ] **Step 2: Run the inspection**

```bash
FIREBASE_SERVICE_ACCOUNT_PATH="$HOME/.config/spicy-desi/firebase-admin.json" \
  api/.venv/bin/python /tmp/preflight_firestore.py
```

Expected: exits 0 with "PRE-FLIGHT PASSED". If it prints `❌ STOP`, do not proceed — coordinate with the dashboard team to understand the existing state.

- [ ] **Step 3: Clean up the temp script**

```bash
rm /tmp/preflight_firestore.py
```

(No commit — this was a one-shot inspection.)

### Task 0.4: Update .gitignore for Firebase artifacts

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Append Firebase patterns**

```bash
cat >> .gitignore <<'EOF'

# Firebase emulator artifacts
firebase-debug.log
firestore-debug.log
ui-debug.log
firebase-export-*/
.firebase/
# Service account JSON (never commit even if accidentally placed in repo)
*firebase-adminsdk*.json
EOF
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore Firebase emulator logs and service-account JSONs"
```

---

## Phase 1 — Dependencies and Firestore client

### Task 1.1: Add Firestore dependencies to api/pyproject.toml

**Files:**
- Modify: `api/pyproject.toml`

- [ ] **Step 1: Add deps**

In `api/pyproject.toml`, find:
```toml
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.32.0",
  "pydantic>=2.9.0",
  "pydantic-settings>=2.6.0",
  "structlog>=24.4.0",
  "httpx>=0.27.0",
  "squareup>=39.0.0",
  "python-dotenv>=1.0.0",
  "twilio>=9.3.0",
]
```

Add two new entries:
```toml
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.32.0",
  "pydantic>=2.9.0",
  "pydantic-settings>=2.6.0",
  "structlog>=24.4.0",
  "httpx>=0.27.0",
  "squareup>=39.0.0",
  "python-dotenv>=1.0.0",
  "twilio>=9.3.0",
  "firebase-admin>=6.5.0",
  "google-cloud-firestore>=2.18.0",
]
```

- [ ] **Step 2: Reinstall deps in venv**

```bash
(cd api && .venv/bin/pip install -e ".[dev]" 2>&1 | tail -5)
```
Expected: completes without errors; firebase-admin and google-cloud-firestore appear as already installed (we put them in the venv during inspection) or get pinned.

- [ ] **Step 3: Verify imports work**

```bash
api/.venv/bin/python -c "from google.cloud import firestore; from firebase_admin import credentials; print('OK')"
```
Expected: `OK`.

- [ ] **Step 4: Run existing tests to confirm no regression**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 75 passed.

- [ ] **Step 5: Commit**

```bash
git add api/pyproject.toml
git commit -m "feat(api): add firebase-admin + google-cloud-firestore deps"
```

### Task 1.2: Add Firestore service-account env to AppSettings

**Files:**
- Modify: `api/app/infrastructure/config.py`

- [ ] **Step 1: Add field**

Find the AppSettings class. Append a new field after `twilio_signing_secret`:
```python
    firebase_service_account_path: str = Field("", alias="FIREBASE_SERVICE_ACCOUNT_PATH")
    firebase_project_id: str = Field("spicy-desi-chicago", alias="FIREBASE_PROJECT_ID")
```

- [ ] **Step 2: Run config tests to confirm no regression**

```bash
(cd api && .venv/bin/pytest tests/unit/test_config.py -v 2>&1 | tail -15)
```
Expected: existing tests pass; new field is permissive (empty default).

- [ ] **Step 3: Commit**

```bash
git add api/app/infrastructure/config.py
git commit -m "feat(api): add FIREBASE_SERVICE_ACCOUNT_PATH + FIREBASE_PROJECT_ID settings"
```

### Task 1.3: Implement FirestoreClient (TDD)

**Files:**
- Create: `api/app/infrastructure/firestore_client.py`
- Test: `api/tests/unit/test_firestore_client.py`

- [ ] **Step 1: Write failing test**

Create `api/tests/unit/test_firestore_client.py`:
```python
"""Tests for FirestoreClient initialization."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.infrastructure.firestore_client import FirestoreClient


def test_init_with_explicit_path(tmp_path):
    """When path is given, FirestoreClient uses it as service account."""
    fake = tmp_path / "fake-sa.json"
    fake.write_text('{"type": "service_account", "project_id": "demo-test"}')
    with patch("app.infrastructure.firestore_client.firestore.Client") as mock_client:
        client = FirestoreClient(project_id="demo-test", service_account_path=str(fake))
        _ = client.db
        mock_client.assert_called_once()


def test_init_with_ambient_credentials():
    """When path is empty, FirestoreClient falls back to ambient credentials
    (works on Cloud Run, GCE, or when GOOGLE_APPLICATION_CREDENTIALS is set)."""
    with patch("app.infrastructure.firestore_client.firestore.Client") as mock_client:
        client = FirestoreClient(project_id="demo-test", service_account_path="")
        _ = client.db
        mock_client.assert_called_once()


def test_emulator_host_respected(monkeypatch):
    """When FIRESTORE_EMULATOR_HOST is set, the client connects to the emulator
    regardless of credentials. Google's client library handles this automatically;
    we just confirm we don't blow up trying to read a real service account."""
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "localhost:8088")
    with patch("app.infrastructure.firestore_client.firestore.Client") as mock_client:
        client = FirestoreClient(project_id="demo-test", service_account_path="")
        _ = client.db
        mock_client.assert_called_once()


def test_db_is_cached():
    """Calling .db twice returns the same client (singleton per FirestoreClient)."""
    with patch("app.infrastructure.firestore_client.firestore.Client") as mock_client:
        mock_client.return_value = object()
        client = FirestoreClient(project_id="demo-test", service_account_path="")
        first = client.db
        second = client.db
        assert first is second
        mock_client.assert_called_once()
```

- [ ] **Step 2: Run to confirm failure**

```bash
(cd api && .venv/bin/pytest tests/unit/test_firestore_client.py -v 2>&1 | tail -15)
```
Expected: `ModuleNotFoundError: No module named 'app.infrastructure.firestore_client'`.

- [ ] **Step 3: Implement**

Create `api/app/infrastructure/firestore_client.py`:
```python
"""Firestore client initialization with three credential paths:

1. Emulator: if FIRESTORE_EMULATOR_HOST env is set, google-cloud-firestore
   auto-detects it and never touches real Firebase. We pass through.
2. Explicit service-account JSON: when service_account_path is non-empty,
   we load credentials from that file. Used on hosts that don't provide
   ambient credentials (Fly, Hetzner).
3. Ambient: when service_account_path is empty AND no emulator host,
   google-auth attempts metadata-server / GOOGLE_APPLICATION_CREDENTIALS.
   Works automatically on Cloud Run.

The client is created lazily on first .db access and cached.
"""
from __future__ import annotations

from google.cloud import firestore
from google.oauth2 import service_account


class FirestoreClient:
    def __init__(self, *, project_id: str, service_account_path: str) -> None:
        self._project_id = project_id
        self._service_account_path = service_account_path
        self._client: firestore.Client | None = None

    @property
    def db(self) -> firestore.Client:
        if self._client is None:
            if self._service_account_path:
                creds = service_account.Credentials.from_service_account_file(
                    self._service_account_path
                )
                self._client = firestore.Client(project=self._project_id, credentials=creds)
            else:
                self._client = firestore.Client(project=self._project_id)
        return self._client
```

- [ ] **Step 4: Run tests**

```bash
(cd api && .venv/bin/pytest tests/unit/test_firestore_client.py -v 2>&1 | tail -10)
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add api/app/infrastructure/firestore_client.py api/tests/unit/test_firestore_client.py
git commit -m "feat(api): add FirestoreClient with emulator/SA/ambient credential paths"
```

### Task 1.4: Emulator config (firebase.json + .firebaserc)

**Files:**
- Create: `firebase.json` (repo root)
- Create: `.firebaserc` (repo root)

- [ ] **Step 1: Create `.firebaserc`**

```json
{
  "projects": {
    "default": "spicy-desi-chicago"
  }
}
```

- [ ] **Step 2: Create `firebase.json`**

```json
{
  "firestore": {
    "rules": "firestore.rules",
    "indexes": "firestore.indexes.json"
  },
  "emulators": {
    "firestore": {
      "port": 8088,
      "host": "127.0.0.1"
    },
    "singleProjectMode": true,
    "ui": {
      "enabled": true,
      "port": 4001
    }
  }
}
```
Port 8088 deliberately avoids 8080 (api default).

- [ ] **Step 3: Create empty firestore.rules and indexes file**

Create `firestore.rules`:
```
// ⚠️ DO NOT DEPLOY THIS FILE TO PRODUCTION ⚠️
//
// This rules file exists ONLY for the local Firestore emulator. Deploying
// it via `firebase deploy --only firestore:rules` would lock out the
// existing dashboard at https://spicydesichicago.com/admin/.
//
// Production rules are owned by the dashboard team. Coordination with them
// happens in Plan 4 (dashboard auth). Until then, never touch production
// rules from this repo.
//
// The Admin SDK used by api/app bypasses rules entirely, so production
// reads/writes from our backend service work regardless of rules. Tests
// run against the emulator with the rules below, which is a default-deny
// — meaningless to our Admin-SDK-using tests but matches what production
// would expect once Plan 4 lands.

rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Default-deny everything. Real rules land in Plan 4.
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```

Create `firestore.indexes.json`:
```json
{
  "indexes": [],
  "fieldOverrides": []
}
```

(Indexes get added in subsequent tasks if any query needs a composite index.)

- [ ] **Step 4: Verify firebase.json parses**

```bash
firebase emulators:start --only firestore --project demo-test &
EMULATOR_PID=$!
sleep 8
# Hit the emulator's metadata endpoint to confirm it's up on 8088
curl -fsS http://localhost:8088/ 2>&1 | head -3 || echo "OK if connection error and 'firestore' is in JSON"
kill $EMULATOR_PID
wait $EMULATOR_PID 2>/dev/null
```
Expected: emulator logs include `Firestore: http://127.0.0.1:8088`.

- [ ] **Step 5: Commit**

```bash
git add firebase.json .firebaserc firestore.rules firestore.indexes.json
git commit -m "feat: Firebase Emulator config for local tests (Firestore on port 8088)

Default port 8080 collides with api service; using 8088 to avoid that.
Strict default-deny rules — real auth/role rules land in Plan 4."
```

---

## Phase 2 — Domain models

### Task 2.1: Call + CallEvent + Outcome (TDD)

**Files:**
- Create: `api/app/domain/call.py`
- Test: `api/tests/unit/test_domain_call.py`

- [ ] **Step 1: Write failing test**

Create `api/tests/unit/test_domain_call.py`:
```python
"""Tests for Call domain models."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.call import Call, CallEvent, Outcome


def test_outcome_values():
    """Enum has exactly the expected outcomes."""
    assert Outcome.IN_PROGRESS == "inProgress"
    assert Outcome.RESOLVED == "resolved"
    assert Outcome.TRANSFERRED == "transferred"
    assert Outcome.MESSAGE_TAKEN == "messageTaken"
    assert Outcome.FAILED == "failed"


def test_call_minimal_construction():
    """Call requires call_sid, started_at, caller_phone, from_number."""
    call = Call(
        call_sid="CA12345",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    assert call.outcome == Outcome.IN_PROGRESS
    assert call.ended_at is None
    assert call.summary is None
    assert call.tools_used == []
    assert call.duration_ms is None


def test_call_to_firestore_uses_camelcase():
    """to_firestore() produces camelCase keys matching dashboard convention."""
    call = Call(
        call_sid="CA12345",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
        tools_used=["listMenuCategories"],
    )
    fs = call.to_firestore()
    assert "callerPhone" in fs
    assert "fromNumber" in fs
    assert "toolsUsed" in fs
    assert "startedAt" in fs
    assert "caller_phone" not in fs  # snake_case must NOT leak
    assert fs["toolsUsed"] == ["listMenuCategories"]


def test_call_from_firestore_round_trip():
    """from_firestore(call.to_firestore()) produces an equivalent Call."""
    original = Call(
        call_sid="CA12345",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
        outcome=Outcome.RESOLVED,
        summary="Asked about hours",
        tools_used=["getPickupToday"],
    )
    recovered = Call.from_firestore(call_sid="CA12345", data=original.to_firestore())
    assert recovered == original


def test_call_event_minimal():
    """CallEvent requires ts and kind; payload defaults to empty."""
    ev = CallEvent(
        ts=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
        kind="toolCalled",
    )
    assert ev.payload == {}


def test_call_event_to_firestore():
    ev = CallEvent(
        ts=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
        kind="toolCalled",
        payload={"tool": "listMenuCategories"},
    )
    fs = ev.to_firestore()
    assert fs == {
        "ts": datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
        "kind": "toolCalled",
        "payload": {"tool": "listMenuCategories"},
    }
```

- [ ] **Step 2: Run to confirm failure**

```bash
(cd api && .venv/bin/pytest tests/unit/test_domain_call.py -v 2>&1 | tail -10)
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `api/app/domain/call.py`:
```python
"""Call and CallEvent domain models.

snake_case Python, camelCase on the wire (Firestore). Translation
happens in to_firestore / from_firestore.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Outcome(StrEnum):
    IN_PROGRESS = "inProgress"
    RESOLVED = "resolved"
    TRANSFERRED = "transferred"
    MESSAGE_TAKEN = "messageTaken"
    FAILED = "failed"


class Call(BaseModel):
    call_sid: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    caller_phone: str
    from_number: str
    outcome: Outcome = Outcome.IN_PROGRESS
    summary: str | None = None
    tools_used: list[str] = Field(default_factory=list)

    def to_firestore(self) -> dict[str, Any]:
        return {
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "durationMs": self.duration_ms,
            "callerPhone": self.caller_phone,
            "fromNumber": self.from_number,
            "outcome": self.outcome.value,
            "summary": self.summary,
            "toolsUsed": list(self.tools_used),
        }

    @classmethod
    def from_firestore(cls, *, call_sid: str, data: dict[str, Any]) -> Call:
        return cls(
            call_sid=call_sid,
            started_at=data["startedAt"],
            ended_at=data.get("endedAt"),
            duration_ms=data.get("durationMs"),
            caller_phone=data["callerPhone"],
            from_number=data["fromNumber"],
            outcome=Outcome(data.get("outcome", Outcome.IN_PROGRESS.value)),
            summary=data.get("summary"),
            tools_used=data.get("toolsUsed", []),
        )


class CallEvent(BaseModel):
    ts: datetime
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_firestore(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "kind": self.kind,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_firestore(cls, data: dict[str, Any]) -> CallEvent:
        return cls(ts=data["ts"], kind=data["kind"], payload=data.get("payload", {}))
```

- [ ] **Step 4: Run tests**

```bash
(cd api && .venv/bin/pytest tests/unit/test_domain_call.py -v 2>&1 | tail -10)
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add api/app/domain/call.py api/tests/unit/test_domain_call.py
git commit -m "feat(api): add Call + CallEvent + Outcome domain models (camelCase on wire)"
```

### Task 2.2: Caller (TDD)

**Files:**
- Create: `api/app/domain/caller.py`
- Test: `api/tests/unit/test_domain_caller.py`

- [ ] **Step 1: Write failing test**

Create `api/tests/unit/test_domain_caller.py`:
```python
"""Tests for Caller domain model."""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.caller import Caller


def test_caller_minimal():
    c = Caller(
        phone="+15551234567",
        first_seen=datetime(2026, 4, 1, tzinfo=timezone.utc),
        last_seen=datetime(2026, 5, 14, tzinfo=timezone.utc),
        call_count=3,
    )
    assert c.last_outcome is None
    assert c.notes == ""


def test_caller_to_firestore_camelcase():
    c = Caller(
        phone="+15551234567",
        first_seen=datetime(2026, 4, 1, tzinfo=timezone.utc),
        last_seen=datetime(2026, 5, 14, tzinfo=timezone.utc),
        call_count=3,
        last_call_sid="CA123",
        last_outcome="messageTaken",
        notes="prefers Hindi",
    )
    fs = c.to_firestore()
    assert "firstSeen" in fs and "lastSeen" in fs and "callCount" in fs
    assert "lastCallSid" in fs and "lastOutcome" in fs
    assert "phone" not in fs  # phone is the doc id, not a field
    assert "call_count" not in fs  # snake_case must not leak


def test_caller_round_trip():
    c = Caller(
        phone="+15551234567",
        first_seen=datetime(2026, 4, 1, tzinfo=timezone.utc),
        last_seen=datetime(2026, 5, 14, tzinfo=timezone.utc),
        call_count=3,
        last_call_sid="CA123",
        last_outcome="resolved",
    )
    recovered = Caller.from_firestore(phone="+15551234567", data=c.to_firestore())
    assert recovered == c
```

- [ ] **Step 2: Run to confirm failure**

```bash
(cd api && .venv/bin/pytest tests/unit/test_domain_caller.py -v 2>&1 | tail -10)
```

- [ ] **Step 3: Implement**

Create `api/app/domain/caller.py`:
```python
"""Caller aggregate (per-phone history)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class Caller(BaseModel):
    phone: str
    first_seen: datetime
    last_seen: datetime
    call_count: int
    last_call_sid: str | None = None
    last_outcome: str | None = None
    notes: str = ""

    def to_firestore(self) -> dict[str, Any]:
        return {
            "firstSeen": self.first_seen,
            "lastSeen": self.last_seen,
            "callCount": self.call_count,
            "lastCallSid": self.last_call_sid,
            "lastOutcome": self.last_outcome,
            "notes": self.notes,
        }

    @classmethod
    def from_firestore(cls, *, phone: str, data: dict[str, Any]) -> Caller:
        return cls(
            phone=phone,
            first_seen=data["firstSeen"],
            last_seen=data["lastSeen"],
            call_count=data["callCount"],
            last_call_sid=data.get("lastCallSid"),
            last_outcome=data.get("lastOutcome"),
            notes=data.get("notes", ""),
        )
```

- [ ] **Step 4: Run tests**

```bash
(cd api && .venv/bin/pytest tests/unit/test_domain_caller.py -v 2>&1 | tail -10)
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add api/app/domain/caller.py api/tests/unit/test_domain_caller.py
git commit -m "feat(api): add Caller domain model"
```

### Task 2.3: Message + OwnerOverride (TDD, both small)

**Files:**
- Create: `api/app/domain/message.py`
- Create: `api/app/domain/owner_override.py`
- Test: `api/tests/unit/test_domain_message.py`
- Test: `api/tests/unit/test_domain_owner_override.py`

- [ ] **Step 1: Write failing tests**

Create `api/tests/unit/test_domain_message.py`:
```python
"""Tests for Message domain model."""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.message import Message, MessageStatus


def test_message_defaults_to_new_status():
    m = Message(
        call_sid="CA123",
        caller_phone="+15551234567",
        reason="catering",
        taken_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    assert m.status == MessageStatus.NEW
    assert m.caller_name is None
    assert m.handled_at is None
    assert m.handled_by is None


def test_message_to_firestore_camelcase():
    m = Message(
        call_sid="CA123",
        caller_phone="+15551234567",
        caller_name="Anika",
        reason="catering for Saturday",
        taken_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    fs = m.to_firestore()
    assert fs["callSid"] == "CA123"
    assert fs["callerPhone"] == "+15551234567"
    assert fs["callerName"] == "Anika"
    assert fs["status"] == "new"
    assert "call_sid" not in fs


def test_message_handled_round_trip():
    m = Message(
        call_sid="CA123",
        caller_phone="+15551234567",
        reason="catering",
        taken_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        status=MessageStatus.HANDLED,
        handled_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        handled_by="Woavythv26dZ7XlJngL7lKakQ7N2",
    )
    recovered = Message.from_firestore(data=m.to_firestore())
    assert recovered == m
```

Create `api/tests/unit/test_domain_owner_override.py`:
```python
"""Tests for OwnerOverride domain model."""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.owner_override import OwnerOverride


def test_inactive_default():
    o = OwnerOverride(
        active=False,
        set_by="uid123",
        set_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    assert o.until_iso is None
    assert o.reason is None


def test_active_with_window():
    o = OwnerOverride(
        active=True,
        until_iso="2026-05-14T18:00:00Z",
        reason="wedding",
        set_by="uid123",
        set_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    fs = o.to_firestore()
    assert fs["active"] is True
    assert fs["untilIso"] == "2026-05-14T18:00:00Z"
    assert fs["setBy"] == "uid123"
    assert "set_by" not in fs


def test_round_trip():
    o = OwnerOverride(
        active=True,
        until_iso="2026-05-14T18:00:00Z",
        reason="wedding",
        set_by="uid123",
        set_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    recovered = OwnerOverride.from_firestore(o.to_firestore())
    assert recovered == o
```

- [ ] **Step 2: Run to confirm failure**

```bash
(cd api && .venv/bin/pytest tests/unit/test_domain_message.py tests/unit/test_domain_owner_override.py -v 2>&1 | tail -15)
```

- [ ] **Step 3: Implement Message**

Create `api/app/domain/message.py`:
```python
"""Message domain model (caller-left messages)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class MessageStatus(StrEnum):
    NEW = "new"
    HANDLED = "handled"


class Message(BaseModel):
    call_sid: str
    caller_phone: str
    caller_name: str | None = None
    reason: str
    taken_at: datetime
    status: MessageStatus = MessageStatus.NEW
    handled_at: datetime | None = None
    handled_by: str | None = None

    def to_firestore(self) -> dict[str, Any]:
        return {
            "callSid": self.call_sid,
            "callerPhone": self.caller_phone,
            "callerName": self.caller_name,
            "reason": self.reason,
            "takenAt": self.taken_at,
            "status": self.status.value,
            "handledAt": self.handled_at,
            "handledBy": self.handled_by,
        }

    @classmethod
    def from_firestore(cls, *, data: dict[str, Any]) -> Message:
        return cls(
            call_sid=data["callSid"],
            caller_phone=data["callerPhone"],
            caller_name=data.get("callerName"),
            reason=data["reason"],
            taken_at=data["takenAt"],
            status=MessageStatus(data.get("status", MessageStatus.NEW.value)),
            handled_at=data.get("handledAt"),
            handled_by=data.get("handledBy"),
        )
```

- [ ] **Step 4: Implement OwnerOverride**

Create `api/app/domain/owner_override.py`:
```python
"""Owner availability override (singleton, doc id 'current')."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class OwnerOverride(BaseModel):
    active: bool
    until_iso: str | None = None
    reason: str | None = None
    set_by: str
    set_at: datetime

    def to_firestore(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "untilIso": self.until_iso,
            "reason": self.reason,
            "setBy": self.set_by,
            "setAt": self.set_at,
        }

    @classmethod
    def from_firestore(cls, data: dict[str, Any]) -> OwnerOverride:
        return cls(
            active=data["active"],
            until_iso=data.get("untilIso"),
            reason=data.get("reason"),
            set_by=data["setBy"],
            set_at=data["setAt"],
        )
```

- [ ] **Step 5: Run tests**

```bash
(cd api && .venv/bin/pytest tests/unit/test_domain_message.py tests/unit/test_domain_owner_override.py -v 2>&1 | tail -10)
```
Expected: 6 passed (3 each).

- [ ] **Step 6: Run full suite to confirm no regression**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: 88 passed (75 existing + 13 new domain tests).

- [ ] **Step 7: Commit**

```bash
git add api/app/domain/message.py api/app/domain/owner_override.py \
        api/tests/unit/test_domain_message.py api/tests/unit/test_domain_owner_override.py
git commit -m "feat(api): add Message + OwnerOverride domain models"
```

---

## Phase 3 — Emulator test fixture

### Task 3.1: Firestore emulator helper

**Files:**
- Create: `api/tests/helpers/firestore_emulator.py`
- Modify: `api/tests/conftest.py`

- [ ] **Step 1: Inspect existing conftest**

```bash
cat api/tests/conftest.py
```
Note its current contents (likely minimal) so we don't disrupt existing fixtures.

- [ ] **Step 2: Create emulator helper**

Create `api/tests/helpers/firestore_emulator.py`:
```python
"""Manage the Firebase Firestore emulator lifecycle for tests.

The emulator is a Java process that runs from `firebase-tools`. We start
it once per test session, point google-cloud-firestore at it via
FIRESTORE_EMULATOR_HOST, and clear all collections between tests for
isolation.

Requirements:
- firebase-tools installed (`brew install firebase-cli`)
- Java 11+ on PATH
- firebase.json at repo root (port 8088)
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from contextlib import closing
from pathlib import Path

EMULATOR_HOST = "127.0.0.1"
EMULATOR_PORT = 8088
PROJECT_ID = "demo-test"


class EmulatorUnavailable(RuntimeError):
    """firebase CLI missing or emulator can't start."""


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True
        except (OSError, socket.timeout):
            return False


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(host, port):
            return
        time.sleep(0.5)
    raise EmulatorUnavailable(
        f"Firestore emulator did not start within {timeout}s on {host}:{port}"
    )


def start_emulator() -> subprocess.Popen[bytes]:
    """Start the Firestore emulator as a subprocess. Caller must terminate it."""
    if shutil.which("firebase") is None:
        raise EmulatorUnavailable(
            "firebase CLI not found. Install with: brew install firebase-cli"
        )

    repo_root = Path(__file__).resolve().parents[3]
    if _port_open(EMULATOR_HOST, EMULATOR_PORT):
        raise EmulatorUnavailable(
            f"Port {EMULATOR_PORT} already in use; stop existing emulator first."
        )

    proc = subprocess.Popen(
        [
            "firebase",
            "emulators:start",
            "--only", "firestore",
            "--project", PROJECT_ID,
        ],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_port(EMULATOR_HOST, EMULATOR_PORT, timeout=45.0)
    except Exception:
        proc.terminate()
        raise

    os.environ["FIRESTORE_EMULATOR_HOST"] = f"{EMULATOR_HOST}:{EMULATOR_PORT}"
    return proc


def stop_emulator(proc: subprocess.Popen[bytes]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    os.environ.pop("FIRESTORE_EMULATOR_HOST", None)


def clear_emulator_data() -> None:
    """Delete all documents from the emulator. Use between tests."""
    import urllib.request

    # The emulator exposes a clear-all endpoint:
    # DELETE /emulator/v1/projects/{project}/databases/(default)/documents
    url = (
        f"http://{EMULATOR_HOST}:{EMULATOR_PORT}"
        f"/emulator/v1/projects/{PROJECT_ID}/databases/(default)/documents"
    )
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req, timeout=5) as resp:
        if resp.status != 200:
            raise RuntimeError(f"emulator clear returned {resp.status}")
```

- [ ] **Step 3: Create empty `__init__.py` for helpers (if not present)**

```bash
test -f api/tests/helpers/__init__.py || touch api/tests/helpers/__init__.py
```

- [ ] **Step 4: Extend conftest.py with fixtures**

Append to `api/tests/conftest.py` (do not replace existing content):
```python


# --- Firestore emulator fixtures --------------------------------------------

import pytest
from google.cloud import firestore

from tests.helpers.firestore_emulator import (
    PROJECT_ID,
    EmulatorUnavailable,
    clear_emulator_data,
    start_emulator,
    stop_emulator,
)


@pytest.fixture(scope="session")
def firestore_emulator():
    """Start the emulator once per test session. Tests opt in by depending
    on this fixture (directly or transitively via firestore_db)."""
    try:
        proc = start_emulator()
    except EmulatorUnavailable as e:
        pytest.skip(f"Firestore emulator unavailable: {e}")
    yield
    stop_emulator(proc)


@pytest.fixture
def firestore_db(firestore_emulator) -> firestore.Client:
    """A fresh Firestore client per test, with all collections cleared
    beforehand. Tests using this fixture are fully isolated."""
    clear_emulator_data()
    return firestore.Client(project=PROJECT_ID)
```

- [ ] **Step 5: Quick smoke test of the fixture**

Add a sanity-check test file at `api/tests/unit/test_emulator_fixture.py`:
```python
"""Quick sanity check that the emulator fixture works."""
from __future__ import annotations


def test_emulator_writes_and_reads(firestore_db):
    """Basic round trip via Firestore client against the emulator."""
    doc_ref = firestore_db.collection("smoke").document("sanity")
    doc_ref.set({"hello": "world"})
    snap = doc_ref.get()
    assert snap.exists
    assert snap.to_dict() == {"hello": "world"}


def test_emulator_clears_between_tests(firestore_db):
    """After clear, no docs from prior test should leak."""
    docs = list(firestore_db.collection("smoke").stream())
    assert docs == []
```

Run:
```bash
(cd api && .venv/bin/pytest tests/unit/test_emulator_fixture.py -v 2>&1 | tail -20)
```
Expected: 2 passed. If `EmulatorUnavailable: firebase CLI not found`, return to Task 0.2.

- [ ] **Step 6: Commit**

```bash
git add api/tests/helpers/__init__.py api/tests/helpers/firestore_emulator.py \
        api/tests/conftest.py api/tests/unit/test_emulator_fixture.py
git commit -m "test(api): Firestore emulator fixture (session-scoped, clears between tests)"
```

---

## Phase 4 — Stores (TDD against emulator)

### Task 4.1: FirestoreCallStore

**Files:**
- Create: `api/app/infrastructure/firestore_call_store.py`
- Test: `api/tests/unit/test_firestore_call_store.py`

- [ ] **Step 1: Write failing tests**

Create `api/tests/unit/test_firestore_call_store.py`:
```python
"""Tests for FirestoreCallStore against the emulator."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.call import Call, CallEvent, Outcome
from app.infrastructure.firestore_call_store import FirestoreCallStore


@pytest.fixture
def store(firestore_db):
    return FirestoreCallStore(client=firestore_db)


def test_record_call_start_creates_doc(store):
    call = Call(
        call_sid="CA1",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    store.record_call_start(call)

    fetched = store.get_call("CA1")
    assert fetched is not None
    assert fetched.call_sid == "CA1"
    assert fetched.outcome == Outcome.IN_PROGRESS


def test_record_call_start_is_idempotent_via_merge(store):
    """Calling record_call_start twice with same call_sid doesn't lose fields
    added by record_call_end (e.g., endedAt set before re-start)."""
    started_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    call = Call(
        call_sid="CA1",
        started_at=started_at,
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    store.record_call_start(call)
    store.record_call_start(call)  # second call

    fetched = store.get_call("CA1")
    assert fetched is not None
    assert fetched.started_at == started_at


def test_record_call_end_sets_ended_and_duration(store):
    call = Call(
        call_sid="CA1",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    store.record_call_start(call)
    ended_at = datetime(2026, 5, 14, 12, 1, 30, tzinfo=timezone.utc)
    store.record_call_end(
        call_sid="CA1",
        ended_at=ended_at,
        outcome=Outcome.RESOLVED,
        duration_ms=90_000,
    )

    fetched = store.get_call("CA1")
    assert fetched is not None
    assert fetched.ended_at == ended_at
    assert fetched.outcome == Outcome.RESOLVED
    assert fetched.duration_ms == 90_000


def test_set_summary(store):
    call = Call(
        call_sid="CA1",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    store.record_call_start(call)
    store.set_summary(call_sid="CA1", summary="Asked about hours and momos")
    fetched = store.get_call("CA1")
    assert fetched is not None
    assert fetched.summary == "Asked about hours and momos"


def test_append_event_creates_call_if_missing(store):
    """append_event upserts the parent call doc with the minimum required
    fields if the call wasn't pre-recorded — preserves event-only writes
    from the existing agent's POST /api/calls/{sid}/event flow."""
    ev = CallEvent(
        ts=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
        kind="toolCalled",
        payload={"tool": "listMenuCategories"},
    )
    store.append_event(
        call_sid="CA-new",
        event=ev,
        caller_phone_for_upsert="+15551234567",
        from_number_for_upsert="+15559998888",
    )
    fetched = store.get_call("CA-new")
    assert fetched is not None
    assert fetched.caller_phone == "+15551234567"
    events = list(store.iter_events("CA-new"))
    assert len(events) == 1
    assert events[0].kind == "toolCalled"


def test_append_event_does_not_clobber_existing_call(store):
    """If the call doc already exists, append_event must not overwrite its
    fields with the upsert defaults."""
    started_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    call = Call(
        call_sid="CA1",
        started_at=started_at,
        caller_phone="+15551234567",
        from_number="+15559998888",
        tools_used=["listMenuCategories"],
    )
    store.record_call_start(call)
    ev = CallEvent(
        ts=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
        kind="transferInitiated",
    )
    store.append_event(
        call_sid="CA1",
        event=ev,
        caller_phone_for_upsert="+19998887777",  # WRONG on purpose — must be ignored
        from_number_for_upsert="+10000000000",
    )
    fetched = store.get_call("CA1")
    assert fetched is not None
    assert fetched.caller_phone == "+15551234567"
    assert fetched.tools_used == ["listMenuCategories"]


def test_get_call_returns_none_when_missing(store):
    assert store.get_call("CA-missing") is None


def test_iter_events_orders_by_ts(store):
    call = Call(
        call_sid="CA1",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        caller_phone="+15551234567",
        from_number="+15559998888",
    )
    store.record_call_start(call)

    second = CallEvent(ts=datetime(2026, 5, 14, 12, 2, tzinfo=timezone.utc), kind="b")
    first = CallEvent(ts=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc), kind="a")
    store.append_event(
        call_sid="CA1",
        event=second,
        caller_phone_for_upsert="+15551234567",
        from_number_for_upsert="+15559998888",
    )
    store.append_event(
        call_sid="CA1",
        event=first,
        caller_phone_for_upsert="+15551234567",
        from_number_for_upsert="+15559998888",
    )

    kinds = [e.kind for e in store.iter_events("CA1")]
    assert kinds == ["a", "b"]
```

- [ ] **Step 2: Run to confirm failures**

```bash
(cd api && .venv/bin/pytest tests/unit/test_firestore_call_store.py -v 2>&1 | tail -25)
```
Expected: `ModuleNotFoundError: ...firestore_call_store`.

- [ ] **Step 3: Implement**

Create `api/app/infrastructure/firestore_call_store.py`:
```python
"""FirestoreCallStore — read/write /calls and /calls/{sid}/events.

camelCase on the wire; snake_case in Python. Translation happens in
the Call / CallEvent models (to_firestore / from_firestore).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterator

from google.cloud import firestore

from app.domain.call import Call, CallEvent, Outcome

CALLS_COLLECTION = "calls"
EVENTS_SUBCOLLECTION = "events"


class FirestoreCallStore:
    def __init__(self, *, client: firestore.Client) -> None:
        self._db = client

    def _call_ref(self, call_sid: str) -> firestore.DocumentReference:
        return self._db.collection(CALLS_COLLECTION).document(call_sid)

    def record_call_start(self, call: Call) -> None:
        """Create or update the call doc. Idempotent — merges with existing."""
        self._call_ref(call.call_sid).set(call.to_firestore(), merge=True)

    def record_call_end(
        self,
        *,
        call_sid: str,
        ended_at: datetime,
        outcome: Outcome,
        duration_ms: int | None,
    ) -> None:
        self._call_ref(call_sid).set(
            {
                "endedAt": ended_at,
                "outcome": outcome.value,
                "durationMs": duration_ms,
            },
            merge=True,
        )

    def set_summary(self, *, call_sid: str, summary: str) -> None:
        self._call_ref(call_sid).set({"summary": summary}, merge=True)

    def get_call(self, call_sid: str) -> Call | None:
        snap = self._call_ref(call_sid).get()
        if not snap.exists:
            return None
        return Call.from_firestore(call_sid=call_sid, data=snap.to_dict() or {})

    def append_event(
        self,
        *,
        call_sid: str,
        event: CallEvent,
        caller_phone_for_upsert: str,
        from_number_for_upsert: str,
    ) -> None:
        """Append a sub-event. If the parent /calls/{sid} doc doesn't exist,
        create it with minimum required fields so foreign-key-ish reads work.

        We use set(..., merge=True) on the parent so existing fields are
        preserved when the doc already exists.
        """
        call_ref = self._call_ref(call_sid)
        snap = call_ref.get()
        if not snap.exists:
            call_ref.set(
                {
                    "startedAt": event.ts,
                    "callerPhone": caller_phone_for_upsert,
                    "fromNumber": from_number_for_upsert,
                    "outcome": Outcome.IN_PROGRESS.value,
                    "toolsUsed": [],
                },
                merge=True,
            )
        call_ref.collection(EVENTS_SUBCOLLECTION).add(event.to_firestore())

    def iter_events(self, call_sid: str) -> Iterator[CallEvent]:
        for snap in (
            self._call_ref(call_sid)
            .collection(EVENTS_SUBCOLLECTION)
            .order_by("ts")
            .stream()
        ):
            data = snap.to_dict() or {}
            yield CallEvent.from_firestore(data)
```

- [ ] **Step 4: Run tests**

```bash
(cd api && .venv/bin/pytest tests/unit/test_firestore_call_store.py -v 2>&1 | tail -20)
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add api/app/infrastructure/firestore_call_store.py api/tests/unit/test_firestore_call_store.py
git commit -m "feat(api): FirestoreCallStore — calls + events subcollection"
```

### Task 4.2: FirestoreCallerStore

**Files:**
- Create: `api/app/infrastructure/firestore_caller_store.py`
- Test: `api/tests/unit/test_firestore_caller_store.py`

- [ ] **Step 1: Write failing tests**

Create `api/tests/unit/test_firestore_caller_store.py`:
```python
"""Tests for FirestoreCallerStore against the emulator."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.caller import Caller
from app.infrastructure.firestore_caller_store import FirestoreCallerStore


@pytest.fixture
def store(firestore_db):
    return FirestoreCallerStore(client=firestore_db)


def test_upsert_first_call_creates_record(store):
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    store.upsert_on_call(
        phone="+15551234567",
        ts=now,
        call_sid="CA1",
        outcome="resolved",
    )
    c = store.get("+15551234567")
    assert c is not None
    assert c.first_seen == now
    assert c.last_seen == now
    assert c.call_count == 1
    assert c.last_call_sid == "CA1"
    assert c.last_outcome == "resolved"


def test_upsert_second_call_increments_count_keeps_first_seen(store):
    first = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    second = datetime(2026, 5, 14, 13, 0, tzinfo=timezone.utc)
    store.upsert_on_call(phone="+15551234567", ts=first, call_sid="CA1", outcome="resolved")
    store.upsert_on_call(phone="+15551234567", ts=second, call_sid="CA2", outcome="messageTaken")

    c = store.get("+15551234567")
    assert c is not None
    assert c.first_seen == first  # unchanged
    assert c.last_seen == second
    assert c.call_count == 2
    assert c.last_call_sid == "CA2"
    assert c.last_outcome == "messageTaken"


def test_get_missing_returns_none(store):
    assert store.get("+19999999999") is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
(cd api && .venv/bin/pytest tests/unit/test_firestore_caller_store.py -v 2>&1 | tail -10)
```

- [ ] **Step 3: Implement**

Create `api/app/infrastructure/firestore_caller_store.py`:
```python
"""FirestoreCallerStore — read/write /callers/{e164}."""
from __future__ import annotations

from datetime import datetime

from google.cloud import firestore

from app.domain.caller import Caller

CALLERS_COLLECTION = "callers"


class FirestoreCallerStore:
    def __init__(self, *, client: firestore.Client) -> None:
        self._db = client

    def _ref(self, phone: str) -> firestore.DocumentReference:
        return self._db.collection(CALLERS_COLLECTION).document(phone)

    def get(self, phone: str) -> Caller | None:
        snap = self._ref(phone).get()
        if not snap.exists:
            return None
        return Caller.from_firestore(phone=phone, data=snap.to_dict() or {})

    def upsert_on_call(
        self,
        *,
        phone: str,
        ts: datetime,
        call_sid: str,
        outcome: str,
    ) -> None:
        """Upsert a caller record on every call. First call sets firstSeen
        and callCount=1; subsequent calls update lastSeen, increment callCount,
        and refresh lastCallSid + lastOutcome. firstSeen is preserved across
        subsequent calls by reading-then-writing inside a transaction (we
        can't use `set(..., merge=True)` to "set only if absent" — merge
        rewrites every field passed)."""
        ref = self._ref(phone)
        self._transactional_upsert(ref, ts=ts, call_sid=call_sid, outcome=outcome)

    @staticmethod
    @firestore.transactional
    def _txn_upsert(
        transaction: firestore.Transaction,
        ref: firestore.DocumentReference,
        ts: datetime,
        call_sid: str,
        outcome: str,
    ) -> None:
        snap = ref.get(transaction=transaction)
        if snap.exists:
            data = snap.to_dict() or {}
            transaction.update(
                ref,
                {
                    "lastSeen": ts,
                    "callCount": (data.get("callCount", 0) or 0) + 1,
                    "lastCallSid": call_sid,
                    "lastOutcome": outcome,
                },
            )
        else:
            transaction.set(
                ref,
                {
                    "firstSeen": ts,
                    "lastSeen": ts,
                    "callCount": 1,
                    "lastCallSid": call_sid,
                    "lastOutcome": outcome,
                    "notes": "",
                },
            )

    def _transactional_upsert(
        self,
        ref: firestore.DocumentReference,
        *,
        ts: datetime,
        call_sid: str,
        outcome: str,
    ) -> None:
        transaction = self._db.transaction()
        self._txn_upsert(transaction, ref, ts, call_sid, outcome)
```

Note: the implementation uses a Firestore transaction so callCount increments correctly under concurrent writes (an issue in production when an agent crash + retry could double-count without atomic update).

- [ ] **Step 4: Run tests**

```bash
(cd api && .venv/bin/pytest tests/unit/test_firestore_caller_store.py -v 2>&1 | tail -10)
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add api/app/infrastructure/firestore_caller_store.py api/tests/unit/test_firestore_caller_store.py
git commit -m "feat(api): FirestoreCallerStore with transactional callCount increment"
```

### Task 4.3: FirestoreMessageStore

**Files:**
- Create: `api/app/infrastructure/firestore_message_store.py`
- Test: `api/tests/unit/test_firestore_message_store.py`

- [ ] **Step 1: Write failing tests**

Create `api/tests/unit/test_firestore_message_store.py`:
```python
"""Tests for FirestoreMessageStore against the emulator."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.message import Message, MessageStatus
from app.infrastructure.firestore_message_store import FirestoreMessageStore


@pytest.fixture
def store(firestore_db):
    return FirestoreMessageStore(client=firestore_db)


def test_create_stores_message_returns_id(store):
    m = Message(
        call_sid="CA1",
        caller_phone="+15551234567",
        caller_name="Anika",
        reason="catering for Saturday",
        taken_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    msg_id = store.create(m)
    assert msg_id  # Firestore-generated id

    fetched = store.get(msg_id)
    assert fetched is not None
    assert fetched.reason == "catering for Saturday"
    assert fetched.status == MessageStatus.NEW


def test_list_unhandled_orders_newest_first(store):
    earlier = Message(
        call_sid="CA1",
        caller_phone="+15551234567",
        reason="first",
        taken_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
    )
    later = Message(
        call_sid="CA2",
        caller_phone="+15559998888",
        reason="second",
        taken_at=datetime(2026, 5, 14, 13, 0, tzinfo=timezone.utc),
    )
    store.create(earlier)
    store.create(later)

    msgs = list(store.list_unhandled(limit=10))
    assert [m.reason for m in msgs] == ["second", "first"]


def test_mark_handled_sets_status_and_metadata(store):
    m = Message(
        call_sid="CA1",
        caller_phone="+15551234567",
        reason="catering",
        taken_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    msg_id = store.create(m)

    handled_at = datetime(2026, 5, 15, tzinfo=timezone.utc)
    store.mark_handled(message_id=msg_id, handled_at=handled_at, handled_by="uid-owner")

    fetched = store.get(msg_id)
    assert fetched is not None
    assert fetched.status == MessageStatus.HANDLED
    assert fetched.handled_at == handled_at
    assert fetched.handled_by == "uid-owner"

    assert list(store.list_unhandled(limit=10)) == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
(cd api && .venv/bin/pytest tests/unit/test_firestore_message_store.py -v 2>&1 | tail -10)
```

- [ ] **Step 3: Implement**

Create `api/app/infrastructure/firestore_message_store.py`:
```python
"""FirestoreMessageStore — read/write /messages."""
from __future__ import annotations

from datetime import datetime
from typing import Iterator

from google.cloud import firestore

from app.domain.message import Message, MessageStatus

MESSAGES_COLLECTION = "messages"


class FirestoreMessageStore:
    def __init__(self, *, client: firestore.Client) -> None:
        self._db = client

    def create(self, message: Message) -> str:
        _, ref = self._db.collection(MESSAGES_COLLECTION).add(message.to_firestore())
        return ref.id

    def get(self, message_id: str) -> Message | None:
        snap = self._db.collection(MESSAGES_COLLECTION).document(message_id).get()
        if not snap.exists:
            return None
        return Message.from_firestore(data=snap.to_dict() or {})

    def list_unhandled(self, *, limit: int = 50) -> Iterator[Message]:
        query = (
            self._db.collection(MESSAGES_COLLECTION)
            .where(filter=firestore.FieldFilter("status", "==", MessageStatus.NEW.value))
            .order_by("takenAt", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        for snap in query.stream():
            yield Message.from_firestore(data=snap.to_dict() or {})

    def mark_handled(
        self,
        *,
        message_id: str,
        handled_at: datetime,
        handled_by: str,
    ) -> None:
        self._db.collection(MESSAGES_COLLECTION).document(message_id).set(
            {
                "status": MessageStatus.HANDLED.value,
                "handledAt": handled_at,
                "handledBy": handled_by,
            },
            merge=True,
        )
```

- [ ] **Step 4: Run tests**

```bash
(cd api && .venv/bin/pytest tests/unit/test_firestore_message_store.py -v 2>&1 | tail -10)
```
Expected: 3 passed.

The `list_unhandled` query needs a composite index on `(status ==, takenAt desc)`. The emulator auto-creates indexes; production needs one declared:

- [ ] **Step 5: Declare the production index**

Update `firestore.indexes.json`:
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
    }
  ],
  "fieldOverrides": []
}
```
(Once deployed, run `firebase deploy --only firestore:indexes` — that's a Plan 4 task; for now we just declare.)

- [ ] **Step 6: Commit**

```bash
git add api/app/infrastructure/firestore_message_store.py \
        api/tests/unit/test_firestore_message_store.py \
        firestore.indexes.json
git commit -m "feat(api): FirestoreMessageStore + production index for unhandled list"
```

### Task 4.4: FirestoreOwnerOverrideStore

**Files:**
- Create: `api/app/infrastructure/firestore_owner_override_store.py`
- Test: `api/tests/unit/test_firestore_owner_override_store.py`

- [ ] **Step 1: Write failing tests**

Create `api/tests/unit/test_firestore_owner_override_store.py`:
```python
"""Tests for FirestoreOwnerOverrideStore."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.owner_override import OwnerOverride
from app.infrastructure.firestore_owner_override_store import FirestoreOwnerOverrideStore


@pytest.fixture
def store(firestore_db):
    return FirestoreOwnerOverrideStore(client=firestore_db)


def test_get_current_when_absent_returns_none(store):
    assert store.get_current() is None


def test_set_then_get_round_trip(store):
    o = OwnerOverride(
        active=True,
        until_iso="2026-05-14T18:00:00Z",
        reason="wedding",
        set_by="uid-owner",
        set_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    store.set(o)
    fetched = store.get_current()
    assert fetched == o


def test_clear_resets_to_inactive(store):
    store.set(
        OwnerOverride(
            active=True,
            until_iso="2026-05-14T18:00:00Z",
            reason="wedding",
            set_by="uid-owner",
            set_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        )
    )
    store.clear(cleared_by="uid-owner")
    fetched = store.get_current()
    assert fetched is not None
    assert fetched.active is False
    assert fetched.until_iso is None
    assert fetched.reason is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
(cd api && .venv/bin/pytest tests/unit/test_firestore_owner_override_store.py -v 2>&1 | tail -10)
```

- [ ] **Step 3: Implement**

Create `api/app/infrastructure/firestore_owner_override_store.py`:
```python
"""FirestoreOwnerOverrideStore — singleton /ownerOverride/current."""
from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore

from app.domain.owner_override import OwnerOverride

COLLECTION = "ownerOverride"
DOC_ID = "current"


class FirestoreOwnerOverrideStore:
    def __init__(self, *, client: firestore.Client) -> None:
        self._db = client

    def _ref(self) -> firestore.DocumentReference:
        return self._db.collection(COLLECTION).document(DOC_ID)

    def get_current(self) -> OwnerOverride | None:
        snap = self._ref().get()
        if not snap.exists:
            return None
        return OwnerOverride.from_firestore(snap.to_dict() or {})

    def set(self, override: OwnerOverride) -> None:
        self._ref().set(override.to_firestore())

    def clear(self, *, cleared_by: str) -> None:
        self._ref().set(
            OwnerOverride(
                active=False,
                until_iso=None,
                reason=None,
                set_by=cleared_by,
                set_at=datetime.now(timezone.utc),
            ).to_firestore()
        )
```

- [ ] **Step 4: Run tests**

```bash
(cd api && .venv/bin/pytest tests/unit/test_firestore_owner_override_store.py -v 2>&1 | tail -10)
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add api/app/infrastructure/firestore_owner_override_store.py \
        api/tests/unit/test_firestore_owner_override_store.py
git commit -m "feat(api): FirestoreOwnerOverrideStore (singleton)"
```

### Task 4.5: Phase 4 regression checkpoint

- [ ] **Step 1: Run full API suite**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -5)
```
Expected: all stores tested; total ~105-110 passed (75 baseline + ~30-35 new). If any pre-existing test regresses, STOP and investigate before moving on.

---

## Phase 5 — Wire stores into AppState and routes

### Task 5.1: Extend AppState with stores

**Files:**
- Modify: `api/app/api/dependencies.py`

- [ ] **Step 1: Read current AppState**

```bash
cat api/app/api/dependencies.py
```
Note the current dataclass fields so the new ones fit cleanly.

- [ ] **Step 2: Add the four store fields**

Add to the AppState dataclass (keep existing fields; just extend):
```python
    call_store: "FirestoreCallStore | None" = None
    caller_store: "FirestoreCallerStore | None" = None
    message_store: "FirestoreMessageStore | None" = None
    owner_override_store: "FirestoreOwnerOverrideStore | None" = None
```
(Optional `None` defaults so existing tests that build AppState without these still work during the transition. We'll flip them to required in a later task once all callers are updated.)

Add the imports under TYPE_CHECKING or directly at top:
```python
from app.infrastructure.firestore_call_store import FirestoreCallStore
from app.infrastructure.firestore_caller_store import FirestoreCallerStore
from app.infrastructure.firestore_message_store import FirestoreMessageStore
from app.infrastructure.firestore_owner_override_store import FirestoreOwnerOverrideStore
```

(Use direct imports — these are real runtime dependencies, not just type hints.)

- [ ] **Step 3: Run tests to confirm no regression**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: all still pass (the new fields default to None).

- [ ] **Step 4: Commit**

```bash
git add api/app/api/dependencies.py
git commit -m "feat(api): add four Firestore stores to AppState (optional during transition)"
```

### Task 5.2: Wire stores into `_build()` in main.py

**Files:**
- Modify: `api/app/main.py`

- [ ] **Step 1: Initialize FirestoreClient and stores at startup**

In `_build()`, after `settings = AppSettings()` and before the AppState construction, add:
```python
from app.infrastructure.firestore_client import FirestoreClient
from app.infrastructure.firestore_call_store import FirestoreCallStore
from app.infrastructure.firestore_caller_store import FirestoreCallerStore
from app.infrastructure.firestore_message_store import FirestoreMessageStore
from app.infrastructure.firestore_owner_override_store import FirestoreOwnerOverrideStore

firestore_client = FirestoreClient(
    project_id=settings.firebase_project_id,
    service_account_path=settings.firebase_service_account_path,
)
db = firestore_client.db
call_store = FirestoreCallStore(client=db)
caller_store = FirestoreCallerStore(client=db)
message_store = FirestoreMessageStore(client=db)
owner_override_store = FirestoreOwnerOverrideStore(client=db)
```

Then add them to the `AppState(...)` instantiation. Read the current file first to see all existing fields:

```bash
grep -A 20 "state = AppState" api/app/main.py
```

Add the four new kwargs to the existing call, preserving every existing field. For example, if the existing call is:
```python
state = AppState(
    tools_shared_secret=settings.tools_shared_secret,
    tenants=load_tenants(settings.configs_dir),
    locations_service=locations_service,
    catalog_service=catalog_service,
    pickup_service=pickup_service,
    event_log=JsonlEventLog(settings.event_log_path),
    square_webhook_signature_key=settings.square_webhook_signature_key,
    square_webhook_url=settings.square_webhook_url,
    twilio=twilio,
    agent_public_url=settings.agent_public_url,
    cors_origins=settings.cors_origin_list,
)
```

…then the new call becomes:
```python
state = AppState(
    tools_shared_secret=settings.tools_shared_secret,
    tenants=load_tenants(settings.configs_dir),
    locations_service=locations_service,
    catalog_service=catalog_service,
    pickup_service=pickup_service,
    event_log=JsonlEventLog(settings.event_log_path),  # removed in Task 5.7
    square_webhook_signature_key=settings.square_webhook_signature_key,
    square_webhook_url=settings.square_webhook_url,
    twilio=twilio,
    agent_public_url=settings.agent_public_url,
    cors_origins=settings.cors_origin_list,
    call_store=call_store,
    caller_store=caller_store,
    message_store=message_store,
    owner_override_store=owner_override_store,
)
```

- [ ] **Step 2: Local boot test**

```bash
(cd api && \
  TOOLS_SHARED_SECRET="$(printf 'x%.0s' {1..32})" \
  SQUARE_ACCESS_TOKEN="test" SQUARE_ENVIRONMENT="sandbox" \
  SQUARE_WEBHOOK_SIGNATURE_KEY="test" \
  CONFIGS_DIR="../configs" \
  FIREBASE_SERVICE_ACCOUNT_PATH="$HOME/.config/spicy-desi/firebase-admin.json" \
  .venv/bin/uvicorn app.main:app --port 18080 &)
sleep 4
curl -fsS http://localhost:18080/healthz
kill %1 2>/dev/null
```
Expected: `{"ok":true}` — confirms the FirestoreClient init doesn't crash the API on boot when the SA path is valid.

- [ ] **Step 3: Run full suite**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: still all passing. Tests that don't depend on Firestore use AppState constructed without stores; tests that DO use Firestore go via the `firestore_db` fixture and build stores directly (per Task 4 patterns).

- [ ] **Step 4: Commit**

```bash
git add api/app/main.py
git commit -m "feat(api): initialize Firestore stores in main._build() and wire to AppState"
```

### Task 5.3: Migrate /api/messages route to FirestoreMessageStore + FirestoreCallStore

**Files:**
- Modify: `api/app/api/routes/messages.py`
- Test: `api/tests/integration/test_messages_route.py` (existing)

- [ ] **Step 1: Read existing test to know what behavior to preserve**

```bash
cat api/tests/integration/test_messages_route.py
```
Note: the route is called as `POST /api/messages` with `X-Tools-Auth` header. It SMS's the owner, optionally SMS's the caller, and appends an event.

- [ ] **Step 2: Update the route handler**

Replace the body of `take_message` with:
```python
from datetime import datetime, timezone

from app.domain.call import CallEvent
from app.domain.message import Message


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
            f'Thanks for calling Spicy Desi. We got your message about "{body.reason}" '
            "and will call you back."
        )
        await state.twilio.send_sms(to=body.callback_number, body=confirmation)

    now = datetime.now(timezone.utc)

    # Primary record: /messages/{autoId}
    msg = Message(
        call_sid=body.call_sid,
        caller_phone=body.callback_number,
        caller_name=body.caller_name,
        reason=body.reason,
        taken_at=now,
    )
    message_id = state.message_store.create(msg)

    # Mirror as a call event so /calls/{sid}/events/ has the full timeline
    state.call_store.append_event(
        call_sid=body.call_sid,
        event=CallEvent(
            ts=now,
            kind="messageTaken",
            payload={
                "messageId": message_id,
                "callerPhone": body.callback_number,
                "callerName": body.caller_name,
                "reason": body.reason,
                "smsSent": sms_sent,
            },
        ),
        caller_phone_for_upsert=body.callback_number,
        from_number_for_upsert=tenant.twilio_number,
    )

    return {"ok": True, "sms_sent": sms_sent, "message_id": message_id}
```

- [ ] **Step 3: Update existing route tests to use Firestore fixture**

Open `api/tests/integration/test_messages_route.py` and check how it currently constructs the test app. It likely uses a fixture that builds AppState without Firestore stores. You need to extend that fixture (or per-test setup) to inject real stores backed by the emulator-backed `firestore_db`.

The right fix depends on what the fixture looks like; common patterns:
- If there's a `build_test_app(event_log: JsonlEventLog | None = None)` factory, add `call_store`, `message_store` args and pass them through.
- If tests build AppState directly, just include the stores.

Concretely, find the fixture and add the stores. For test isolation, each integration test using messages route should depend on `firestore_db` so it gets a clean DB.

Also update the assertions: tests likely read from `event_log.read_all()` to check that an event was appended. Replace those with reads from the Firestore stores:
```python
# Was: assert any(e["kind"] == "message_taken" for e in await state.event_log.read_all())
# Now: assert state.call_store.get_call("CA1").outcome == Outcome.IN_PROGRESS  # or similar
#      assert len(list(state.call_store.iter_events("CA1"))) == 1
#      msgs = list(state.message_store.list_unhandled())
#      assert any(m.reason == body.reason for m in msgs)
```

- [ ] **Step 4: Run the test**

```bash
(cd api && .venv/bin/pytest tests/integration/test_messages_route.py -v 2>&1 | tail -25)
```
Expected: all passing.

- [ ] **Step 5: Full suite check**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add api/app/api/routes/messages.py api/tests/integration/test_messages_route.py
git commit -m "feat(api): /api/messages writes to Firestore (Message + call event mirror)"
```

### Task 5.4: Migrate /api/calls/{sid}/event route to FirestoreCallStore

**Files:**
- Modify: `api/app/api/routes/events.py`
- Test: `api/tests/integration/test_events_route.py`

- [ ] **Step 1: Update route**

Replace `api/app/api/routes/events.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.dependencies import get_state, require_tools_auth
from app.domain.call import CallEvent

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


class EventBody(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    # Caller phone + from number aren't required because some events
    # arrive after call_started; the call doc already exists. They're
    # only used for the upsert-when-missing path.
    caller_phone: str = ""
    from_number: str = ""


@router.post("/calls/{call_sid}/event", status_code=202)
async def append_call_event(request: Request, call_sid: str, body: EventBody) -> dict[str, Any]:
    state = get_state(request)
    state.call_store.append_event(
        call_sid=call_sid,
        event=CallEvent(
            ts=datetime.now(timezone.utc),
            kind=body.kind,
            payload=body.payload,
        ),
        caller_phone_for_upsert=body.caller_phone or "+0",
        from_number_for_upsert=body.from_number or "+0",
    )
    return {"ok": True}
```

Note: `"+0"` is a placeholder when the agent doesn't supply caller info on a downstream event — better than a hard-error since this is an additive flow. Real call_started events (Plan 2b) will always supply both fields.

- [ ] **Step 2: Update tests**

Open `api/tests/integration/test_events_route.py`. Replace JsonlEventLog assertions with FirestoreCallStore assertions. The contract is:
- POST `/api/calls/{sid}/event` with kind + payload
- Response: `{"ok": true}` with status 202
- Assertion: `list(state.call_store.iter_events(call_sid))` contains the event

- [ ] **Step 3: Run**

```bash
(cd api && .venv/bin/pytest tests/integration/test_events_route.py -v 2>&1 | tail -15)
```
Expected: passing.

- [ ] **Step 4: Full suite**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```

- [ ] **Step 5: Commit**

```bash
git add api/app/api/routes/events.py api/tests/integration/test_events_route.py
git commit -m "feat(api): /api/calls/{sid}/event writes to FirestoreCallStore subcollection"
```

### Task 5.5: Migrate /api/callers/history to FirestoreCallerStore + FirestoreCallStore

**Files:**
- Modify: `api/app/api/routes/callers.py`
- Test: `api/tests/integration/test_callers_route.py`

- [ ] **Step 1: Rewrite the route**

Replace `api/app/api/routes/callers.py`:
```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_state, require_tools_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_tools_auth)])


@router.get("/callers/history")
async def caller_history(
    request: Request,
    phone: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    """Return a brief history of prior interactions for a given caller.

    Used by the agent at call start so it can greet returning customers
    differently. Backed by /callers/{phone} aggregate + most recent
    events from their most recent call.
    """
    _ = limit  # reserved for future use (event paging); aggregate is single doc today
    state = get_state(request)
    caller = state.caller_store.get(phone)
    if caller is None:
        return {
            "phone": phone,
            "is_returning": False,
            "call_count": 0,
            "events": [],
        }
    events: list[dict[str, Any]] = []
    if caller.last_call_sid:
        for ev in state.call_store.iter_events(caller.last_call_sid):
            events.append({
                "ts": ev.ts.timestamp(),
                "kind": ev.kind,
                "call_sid": caller.last_call_sid,
                "summary": _short_summary(ev.kind, ev.payload),
            })
    return {
        "phone": phone,
        "is_returning": True,
        "call_count": caller.call_count,
        "events": events,
    }


def _short_summary(kind: str, payload: dict[str, Any]) -> str:
    if kind == "messageTaken":
        return f"Left a message: {(payload.get('reason') or '')[:80]}"
    if kind == "transferInitiated":
        return "Asked to be transferred"
    if kind == "smsLinkSent":
        return f"Sent {payload.get('kind')} link via SMS"
    if kind == "callStarted":
        return "Called previously"
    return kind
```

- [ ] **Step 2: Update tests**

Open `api/tests/integration/test_callers_route.py`. The test needs to seed Firestore (via FirestoreCallerStore + FirestoreCallStore) then call the route. Match the response shape (`is_returning`, `call_count`, `events`).

- [ ] **Step 3: Run**

```bash
(cd api && .venv/bin/pytest tests/integration/test_callers_route.py -v 2>&1 | tail -15)
```

- [ ] **Step 4: Full suite + commit**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
git add api/app/api/routes/callers.py api/tests/integration/test_callers_route.py
git commit -m "feat(api): /api/callers/history reads FirestoreCallerStore + recent events"
```

### Task 5.6: Migrate transfer_decision_service to consult owner override

**Files:**
- Modify: `api/app/services/transfer_decision_service.py`
- Test: `api/tests/unit/test_transfer_decision_service.py`

- [ ] **Step 1: Read the existing service**

```bash
cat api/app/services/transfer_decision_service.py
```
Note the exact constructor signature and the `decide()` body. You will preserve the existing decision logic verbatim and only add the override check as a guard before it runs.

- [ ] **Step 2: Update service — surgical edit**

Add `owner_override_store` to the constructor as a new keyword-only parameter (defaulting to None so existing tests that don't pass it still work):

Find the existing `__init__` and add the new parameter at the end of its keyword-only args. Add `from app.infrastructure.firestore_owner_override_store import FirestoreOwnerOverrideStore` to the imports.

Then in `decide()` (or whatever the public method is called — read the file to confirm), add this block as the FIRST executable statement of the method body, BEFORE all existing logic:

```python
        # Check day-of override first; if active and not expired, force take_message.
        if self._owner_override_store is not None:
            override = self._owner_override_store.get_current()
            if override and override.active and override.until_iso:
                from datetime import datetime
                until = datetime.fromisoformat(override.until_iso.replace("Z", "+00:00"))
                if self._clock.now_utc() < until:
                    return TransferDecision(action="take_message", target=None)
```

DO NOT modify or replace any existing decision logic — only insert the override check at the top.

- [ ] **Step 3: Wire in main.py**

In `api/app/main.py` `_build()`, find where `TransferDecisionService` (or the transfer-related service) is constructed. Add `owner_override_store=owner_override_store` to that call. If transfer logic is currently inline in routes rather than a service, the new check should live in the service when you extract it — for this plan, find the smallest existing seam and add it there.

- [ ] **Step 4: Add tests**

Read the existing test file to see how the service is instantiated in tests:
```bash
cat api/tests/unit/test_transfer_decision_service.py
```

Append two new tests using a hand-written stub for the override store (no emulator needed since we're testing the service in isolation):

```python
from datetime import datetime, timedelta, timezone
from app.domain.owner_override import OwnerOverride


class _StubOverrideStore:
    def __init__(self, override: OwnerOverride | None) -> None:
        self._override = override

    def get_current(self) -> OwnerOverride | None:
        return self._override


def test_active_override_forces_take_message():
    # GIVEN weekly schedule says owner IS available right now
    # but override is active until +2h
    until = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    override_store = _StubOverrideStore(
        OwnerOverride(
            active=True,
            until_iso=until,
            reason="wedding",
            set_by="uid-owner",
            set_at=datetime.now(timezone.utc),
        )
    )
    # Construct the service with whatever args its existing tests use,
    # PLUS owner_override_store=override_store.
    # Then call .decide(...) and assert result.action == "take_message".
    # (Fill in tenant / clock setup per the existing test pattern in this file.)
    ...


def test_expired_override_ignored():
    # GIVEN override active=True but until_iso is in the past
    until = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    override_store = _StubOverrideStore(
        OwnerOverride(
            active=True,
            until_iso=until,
            reason="wedding",
            set_by="uid-owner",
            set_at=datetime.now(timezone.utc) - timedelta(hours=3),
        )
    )
    # Construct the service with owner_override_store=override_store.
    # Assert decision falls through to the weekly schedule (i.e., same result
    # as if the override store returned None).
    ...
```

The `...` inside each test body is intentional — fill in the construction details by mirroring the existing tests in this file (their fixtures, clock setup, tenant data). The two new tests exist to assert that the override path is consulted; the existing tests still validate the weekly-schedule path.

- [ ] **Step 5: Run + commit**

```bash
(cd api && .venv/bin/pytest tests/unit/test_transfer_decision_service.py -v 2>&1 | tail -15)
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
git add api/app/services/transfer_decision_service.py \
        api/app/main.py \
        api/tests/unit/test_transfer_decision_service.py
git commit -m "feat(api): TransferDecisionService consults Firestore owner override"
```

### Task 5.7: Remove JsonlEventLog from AppState (now unused)

**Files:**
- Modify: `api/app/api/dependencies.py`
- Modify: `api/app/main.py`
- Delete: `api/app/infrastructure/event_log.py`
- Delete: `api/tests/unit/test_event_log.py`

- [ ] **Step 1: Verify no callers remain**

```bash
grep -rn "event_log\|JsonlEventLog" api/app/ api/tests/ | grep -v __pycache__
```
Expected: only legitimate uses are in the files about to be removed. If any production-path call remains, fix that route first before deleting.

- [ ] **Step 2: Drop the field + delete files**

In `api/app/api/dependencies.py`, remove `event_log: JsonlEventLog`. In `api/app/main.py`, remove the JsonlEventLog import and instantiation. Delete `event_log.py` and `test_event_log.py`.

- [ ] **Step 3: Make the Firestore stores REQUIRED (not Optional)**

Now that everything writes to Firestore, the optional defaults from Task 5.1 should be removed:
```python
call_store: FirestoreCallStore
caller_store: FirestoreCallerStore
message_store: FirestoreMessageStore
owner_override_store: FirestoreOwnerOverrideStore
```

- [ ] **Step 4: Run full suite + commit**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -3)
```
Expected: all passing.

```bash
git add api/app/api/dependencies.py api/app/main.py
git rm api/app/infrastructure/event_log.py api/tests/unit/test_event_log.py
git commit -m "refactor(api): remove JsonlEventLog (replaced by Firestore stores)

Firestore stores in AppState are now required fields (no more Optional
defaults). All routes write to Firestore; JSONL is no longer the
backing store for any production code path."
```

---

## Phase 6 — Backfill migration

### Task 6.1: One-shot backfill script

**Files:**
- Create: `api/scripts/backfill_jsonl_to_firestore.py`
- Create: `api/scripts/__init__.py` (empty)

- [ ] **Step 1: Write the script**

Create `api/scripts/backfill_jsonl_to_firestore.py`:
```python
"""Backfill api/data/events.jsonl into Firestore.

Idempotent — safe to re-run. Reconstructs:
- /calls/{sid} from call_started + the rest
- /calls/{sid}/events/ subcollection
- /callers/{phone}
- /messages/{autoId} (for message_taken events that lack a primary record)

DATA-SAFETY GUARANTEES:
- This script only ever writes to OUR_COLLECTIONS = {"calls","callers","messages"}.
- The --clear flag refuses to delete any collection not in OUR_COLLECTIONS.
- Before doing any write, the script checks that the target collections
  do not contain dashboard-owned field names (e.g., "actorUid") — if they
  do, it aborts because that's a sign we're pointing at the wrong project.

Usage:
    FIREBASE_SERVICE_ACCOUNT_PATH=~/.config/spicy-desi/firebase-admin.json \\
    FIREBASE_PROJECT_ID=spicy-desi-chicago \\
    api/.venv/bin/python -m scripts.backfill_jsonl_to_firestore api/data/events.jsonl

Run from inside api/ so the module import works:
    cd api && \\
    FIREBASE_SERVICE_ACCOUNT_PATH=... .venv/bin/python -m scripts.backfill_jsonl_to_firestore data/events.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.domain.call import Call, CallEvent, Outcome
from app.domain.caller import Caller
from app.domain.message import Message
from app.infrastructure.firestore_call_store import FirestoreCallStore
from app.infrastructure.firestore_caller_store import FirestoreCallerStore
from app.infrastructure.firestore_client import FirestoreClient
from app.infrastructure.firestore_message_store import FirestoreMessageStore

OUR_COLLECTIONS: frozenset[str] = frozenset({"calls", "callers", "messages"})
DASHBOARD_FIELD_FINGERPRINTS: frozenset[str] = frozenset(
    {"actorUid", "actorEmail", "squareItemId", "sortOrder", "minQty", "checklistTemplates"}
)


def _abort_if_collections_look_like_dashboard(db) -> None:
    """Sanity check: if any 'our' collection in the target project contains
    documents with dashboard field names, abort — we're pointed at the wrong
    project or someone else owns these paths."""
    for coll_name in OUR_COLLECTIONS:
        docs = list(db.collection(coll_name).limit(3).stream())
        for d in docs:
            data = d.to_dict() or {}
            hits = DASHBOARD_FIELD_FINGERPRINTS & set(data.keys())
            if hits:
                raise SystemExit(
                    f"REFUSING TO RUN: collection /{coll_name} contains dashboard-owned "
                    f"fields {sorted(hits)}. This script is not pointed at the right project."
                )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("jsonl_path", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.jsonl_path.exists():
        print(f"No file at {args.jsonl_path} — nothing to backfill", file=sys.stderr)
        return 0

    client = FirestoreClient(
        project_id=os.environ.get("FIREBASE_PROJECT_ID", "spicy-desi-chicago"),
        service_account_path=os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", ""),
    )

    # Safety: refuse to proceed if our target collections contain
    # dashboard-owned data (means we're pointed at the wrong project,
    # or someone else writes to these paths).
    _abort_if_collections_look_like_dashboard(client.db)

    call_store = FirestoreCallStore(client=client.db)
    caller_store = FirestoreCallerStore(client=client.db)
    msg_store = FirestoreMessageStore(client=client.db)

    seen_calls: set[str] = set()
    seen_phones: set[str] = set()
    msg_count = 0
    event_count = 0

    with args.jsonl_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            call_sid = ev.get("call_sid") or ""
            kind = ev.get("kind") or ""
            payload = ev.get("payload") or {}
            ts_float = ev.get("ts")
            ts = datetime.fromtimestamp(ts_float, tz=timezone.utc) if ts_float else datetime.now(timezone.utc)
            caller_phone = (
                payload.get("from_phone")
                or payload.get("callback_number")
                or ev.get("from_phone")
                or "+0"
            )

            if args.dry_run:
                event_count += 1
                continue

            # Append the event to the call's subcollection (creates parent if absent)
            call_store.append_event(
                call_sid=call_sid,
                event=CallEvent(ts=ts, kind=kind, payload=payload),
                caller_phone_for_upsert=caller_phone,
                from_number_for_upsert=payload.get("to") or "+0",
            )
            event_count += 1
            seen_calls.add(call_sid)

            if caller_phone and caller_phone != "+0" and caller_phone not in seen_phones:
                caller_store.upsert_on_call(
                    phone=caller_phone, ts=ts, call_sid=call_sid, outcome="backfilled"
                )
                seen_phones.add(caller_phone)

            if kind == "message_taken":
                msg_store.create(
                    Message(
                        call_sid=call_sid,
                        caller_phone=caller_phone,
                        caller_name=payload.get("caller_name"),
                        reason=payload.get("reason", ""),
                        taken_at=ts,
                    )
                )
                msg_count += 1

    print(
        f"Backfill {'DRY-RUN' if args.dry_run else 'COMPLETE'}: "
        f"{event_count} events, {len(seen_calls)} calls, "
        f"{len(seen_phones)} callers, {msg_count} messages"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

```bash
touch api/scripts/__init__.py
```

- [ ] **Step 2: Test on a local fake events.jsonl (NOT against real Firestore)**

Start the emulator manually so we don't hit prod:
```bash
firebase emulators:start --only firestore --project demo-test &
EMU=$!
sleep 8

# Build a small synthetic events.jsonl
cat > /tmp/test-events.jsonl <<'EOF'
{"call_sid":"CA1","kind":"call_started","ts":1715693000.0,"payload":{"from_phone":"+15551234567"}}
{"call_sid":"CA1","kind":"message_taken","ts":1715693060.0,"payload":{"call_sid":"CA1","callback_number":"+15551234567","reason":"catering"}}
EOF

FIRESTORE_EMULATOR_HOST=localhost:8088 \
FIREBASE_PROJECT_ID=demo-test \
  api/.venv/bin/python -m scripts.backfill_jsonl_to_firestore /tmp/test-events.jsonl 2>&1
# Expected: "Backfill COMPLETE: 2 events, 1 calls, 1 callers, 1 messages"

# Run again to verify idempotency
FIRESTORE_EMULATOR_HOST=localhost:8088 \
FIREBASE_PROJECT_ID=demo-test \
  api/.venv/bin/python -m scripts.backfill_jsonl_to_firestore /tmp/test-events.jsonl 2>&1
# Expected: same counts. Note: events subcollection will double — that's a known limitation;
# document it in the script docstring or add a manual --reset flag.

kill $EMU
rm -f /tmp/test-events.jsonl
```

If you need idempotency, the cheapest fix is to add a `--clear` flag that wipes the relevant collections before backfilling. Add it now:

```python
parser.add_argument("--clear", action="store_true", help="Delete /calls, /callers, /messages first (DESTRUCTIVE)")
```
And in `main()`:
```python
if args.clear and not args.dry_run:
    # Hardcoded list — we use OUR_COLLECTIONS so this CAN'T be parameterized
    # to a dashboard-owned collection name by accident.
    for coll in OUR_COLLECTIONS:
        # Streaming delete in batches
        docs = list(client.db.collection(coll).limit(500).stream())
        while docs:
            batch = client.db.batch()
            for doc in docs:
                batch.delete(doc.reference)
            batch.commit()
            docs = list(client.db.collection(coll).limit(500).stream())
```

Re-run with --clear:
```bash
FIRESTORE_EMULATOR_HOST=localhost:8088 FIREBASE_PROJECT_ID=demo-test \
  api/.venv/bin/python -m scripts.backfill_jsonl_to_firestore --clear /tmp/test-events.jsonl
```

- [ ] **Step 3: Commit**

```bash
git add api/scripts/__init__.py api/scripts/backfill_jsonl_to_firestore.py
git commit -m "feat(api): one-shot backfill script for events.jsonl -> Firestore

Idempotent with --clear flag. Reconstructs /calls, /callers, /messages
from the legacy JSONL event log. Tested against emulator with synthetic
data; --dry-run prints counts without writing."
```

- [ ] **Step 4: (Manual, deferred) Run against production**

When you're ready to put real data in (post-deploy), run:
```bash
cd api && \
  FIREBASE_PROJECT_ID=spicy-desi-chicago \
  FIREBASE_SERVICE_ACCOUNT_PATH=$HOME/.config/spicy-desi/firebase-admin.json \
  .venv/bin/python -m scripts.backfill_jsonl_to_firestore data/events.jsonl --dry-run
```
Verify counts, then drop --dry-run.

This step is NOT part of the plan execution — it's an operational note for when you have real call data to migrate.

---

## Phase 7 — Docker + docs

### Task 7.1: docker-compose passes Firestore env

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Add the env to compose**

In the `api` service `environment:` block in `docker-compose.yml`, append:
```yaml
      FIREBASE_SERVICE_ACCOUNT_PATH: ${FIREBASE_SERVICE_ACCOUNT_PATH:-/run/firebase/sa.json}
      FIREBASE_PROJECT_ID: ${FIREBASE_PROJECT_ID:-spicy-desi-chicago}
```

Add a volume mount for the service account file:
```yaml
    volumes:
      - ${FIREBASE_SERVICE_ACCOUNT_HOST_PATH:-./.empty}:/run/firebase/sa.json:ro
```

Note: the `:-./.empty` default avoids a hard failure when running compose without a Firebase setup. Create an empty placeholder if needed:
```bash
touch .empty
```

- [ ] **Step 2: Add to .env.example**

Append:
```bash
# === Firebase / Firestore ===
FIREBASE_PROJECT_ID=spicy-desi-chicago
# Absolute path on the HOST to the service-account JSON; mounted into the api container at /run/firebase/sa.json
FIREBASE_SERVICE_ACCOUNT_HOST_PATH=/Users/YOU/.config/spicy-desi/firebase-admin.json
FIREBASE_SERVICE_ACCOUNT_PATH=/run/firebase/sa.json
```

- [ ] **Step 3: Skip running compose now (Docker may not be running)**

If Docker is running, do a smoke test:
```bash
# Build .env.local with Firebase paths (do NOT commit it)
cat agent/.env api/.env > .env.local
echo "FIREBASE_PROJECT_ID=spicy-desi-chicago" >> .env.local
echo "FIREBASE_SERVICE_ACCOUNT_HOST_PATH=$HOME/.config/spicy-desi/firebase-admin.json" >> .env.local
echo "FIREBASE_SERVICE_ACCOUNT_PATH=/run/firebase/sa.json" >> .env.local

docker compose --env-file .env.local up -d --build
sleep 12
docker compose ps
curl -fsS http://localhost:8080/healthz
docker compose --env-file .env.local down
rm -f .env.local
```
Expected: both services healthy, healthz returns `{"ok":true}`. If Docker isn't running, skip — Fly's remote build will validate at deploy time.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example .empty
git commit -m "feat(compose): mount Firebase service account into api container

FIREBASE_SERVICE_ACCOUNT_HOST_PATH on the host -> /run/firebase/sa.json
in the container (read-only). FIREBASE_PROJECT_ID and the in-container
path go via env."
```

### Task 7.2: README — Firestore setup section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append a Firestore section** after the "Security model" block:

```markdown
## Firestore persistence

The API service uses Cloud Firestore (project `spicy-desi-chicago`) for call records, callers, messages, and owner-availability overrides. Existing dashboard collections (`activityLogs`, `menuItems`, `stores`, etc.) are untouched.

### New collections (this plan)

| Collection | Doc ID | Purpose |
|---|---|---|
| `/calls/{callSid}` | Twilio CallSid | One doc per call |
| `/calls/{callSid}/events/{autoId}` | auto | Per-call event log (tool calls, transfers, SMS) |
| `/callers/{e164}` | phone number | Caller aggregate (callCount, lastSeen, lastOutcome) |
| `/messages/{autoId}` | auto | Caller-left callback requests |
| `/ownerOverride/current` | `current` | Owner availability override (singleton) |
| `/dailyStats/{YYYY-MM-DD}` | date | Nightly aggregate (not yet computed) |

### Local development

Tests run against the **Firebase Emulator Suite** — no real Firebase access needed.

```bash
brew install firebase-cli            # one-time
brew install openjdk@17              # if not already (Java 11+ required)

# Tests auto-start the emulator via a session-scoped pytest fixture;
# no manual emulator launch required.
(cd api && .venv/bin/pytest tests/)
```

To run the emulator manually (for poking around with the Firestore UI on http://localhost:4001):

```bash
firebase emulators:start --only firestore --project demo-test
```

### Production credentials

The API service authenticates to Firestore via a service-account JSON loaded from `FIREBASE_SERVICE_ACCOUNT_PATH`. Recommended host location: `~/.config/spicy-desi/firebase-admin.json` (file mode 600).

Cloud Run sets ambient credentials automatically — leave the env var empty there. Fly.io and other hosts: paste the JSON into a Fly secret (`flyctl secrets set FIREBASE_SERVICE_ACCOUNT_JSON="@$HOME/.config/spicy-desi/firebase-admin.json"` — Fly recognizes `@path` to load file contents).

### Backfilling historical JSONL

If you have an existing `api/data/events.jsonl` you want imported into Firestore:

```bash
cd api && \
  FIREBASE_PROJECT_ID=spicy-desi-chicago \
  FIREBASE_SERVICE_ACCOUNT_PATH=$HOME/.config/spicy-desi/firebase-admin.json \
  .venv/bin/python -m scripts.backfill_jsonl_to_firestore data/events.jsonl --dry-run
# Verify counts, then drop --dry-run.
# Add --clear to wipe the new collections before re-importing (DESTRUCTIVE).
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: Firestore setup section in README (emulator, prod creds, backfill)"
```

### Task 7.3: Final regression + push branch

**Files:** None.

- [ ] **Step 1: Final test run**

```bash
(cd api && .venv/bin/pytest tests/ -q 2>&1 | tail -5)
(cd agent && .venv/bin/pytest tests/ -q 2>&1 | tail -5)
```
Expected: agent still 66 passed (unchanged), api well above original 75 (likely 110+).

- [ ] **Step 2: Push branch**

```bash
git push -u origin feature/firestore-persistence 2>&1 | tail -5
```

- [ ] **Step 3: Note the PR-create URL** — printed by `git push`. Open the PR when ready.

---

## Verification

End-to-end verification per phase:

1. **Phase 1 (client + config):** `from app.infrastructure.firestore_client import FirestoreClient` imports cleanly; `AppSettings` accepts `FIREBASE_SERVICE_ACCOUNT_PATH` without errors.
2. **Phase 2 (models):** All 13 domain-model tests pass; round-trip `to_firestore`/`from_firestore` is exact.
3. **Phase 3 (emulator):** `pytest tests/unit/test_emulator_fixture.py` passes (emulator boots, accepts writes, clears between tests).
4. **Phase 4 (stores):** All 4 store test files pass (~17 tests).
5. **Phase 5 (routes):** Integration tests for messages, events, callers, transfers all pass against the emulator. Pre-existing JSONL-based tests are gone; their behavior is preserved via Firestore-backed equivalents.
6. **Phase 6 (backfill):** Script runs against emulator with synthetic JSONL and reports correct counts. `--clear` works. Idempotent with `--clear`.
7. **Phase 7 (docs):** README has a Firestore section. docker-compose mounts the SA file. .env.example documents the new env vars.

Full-system check: `(cd api && .venv/bin/pytest tests/ -q)` shows all tests passing. No `event_log` references remain in `api/app/`. `JsonlEventLog` is deleted. The agent service is unchanged (still calls `/api/calls/{sid}/event` and `/api/messages` — but those now write to Firestore).

---

## What's next (separate plans)

- **Plan 2b: Agent adoption + end-of-call summary** — agent calls new `/api/calls/{sid}/start`, `/end`, `/summary` routes (which we'd add as part of 2b or as a small addendum); LLM summary generation before WebSocket close.
- **Plan 3: Voice fallback lines + reliable event retry** — roadmap items 0.1 + 0.2.
- **Plan 4: Dashboard auth + rate limiting + Firebase Auth ID tokens** — finishes the 0.0c security baseline.
- **Plan 5: Move pickup_state.json to Firestore** — small follow-up; consistency win.
- **Plan 6: Compute dailyStats** — nightly job (Cloud Scheduler or APScheduler in-process).
