# Spicy Desi Voice Agent

AI phone agent for Spicy Desi Chicago. Pipecat + Groq + Cartesia voice loop on top of a FastAPI/Python service backed by Square Catalog & Locations.

## Repo layout

- `api/` — FastAPI Python service the voice agent calls (**shipped**)
- `agent/` — Pipecat voice agent — Twilio Media Streams + Groq + Deepgram + Cartesia (**shipped**)
- `configs/<tenant>/` — per-tenant config and FAQ
- `deploy/` — systemd + Caddy artifacts (unused — see hosting note below)
- `docs/superpowers/specs/` — design specs
- `docs/superpowers/plans/` — implementation plans

## Quick start

### Option A: Docker Compose (recommended — boots both services together)

Requires Docker (Docker Desktop, OrbStack, or equivalent).

```bash
# Fill in real values for both env files first
cp agent/.env.example agent/.env
cp api/.env.example api/.env
# Build a merged .env.local for compose (skip if values have literal $ — escape as $$)
{
  grep -E "^[A-Z_]+=" agent/.env
  grep -E "^[A-Z_]+=" api/.env
} | awk -F= '!seen[$1]++' > .env.local
sed -i.bak 's|^TOOLS_API_BASE=.*|TOOLS_API_BASE=http://api:8080|' .env.local && rm .env.local.bak

docker compose --env-file .env.local up --build
```

Services land at:
- API: `http://localhost:8080`
- Agent: `http://localhost:8090`

### Option B: Native Python (faster iteration on the API)

```bash
cd api
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill in real keys
uvicorn app.main:app --reload --port 8080
```

Then in a second terminal:

```bash
curl http://localhost:8080/healthz
curl -H "X-Tools-Auth: $TOOLS_SHARED_SECRET" \
     "http://localhost:8080/api/locations?tenant=spicy-desi"
```

The agent runs the same way from `agent/` on port 8090.

## Tests

```bash
(cd api   && .venv/bin/pytest tests/ -q)   # 75 passed
(cd agent && .venv/bin/pytest tests/ -q)   # 66 passed
```

All hermetic — no live Square / Twilio / Groq calls.

## Security model

- All Twilio webhooks (`/twilio/inbound`, `/twilio/dial-owner`, `/twilio/dial-owner-fallback`) are HMAC-validated via `X-Twilio-Signature` using `TWILIO_AUTH_TOKEN`.
- Square webhook (`/api/webhooks/square`) is HMAC-validated via `X-Square-HmacSha256-Signature`.
- **Production gate**: when `APP_ENV=production` and `TWILIO_AUTH_TOKEN` is empty, the agent refuses to boot (RuntimeError). This prevents a "forgot the secret" deploy from silently running with signature verification disabled. In `APP_ENV=development` (the local default) an empty token logs a WARN and the verifier accepts all requests — fine for local dev where Twilio isn't in the picture.
- CORS pinned to `https://spicydesichicago.com` on the API.

## Firestore persistence

Operational data (calls, callers, messages, owner-override decisions, transfer audit) lives in **Cloud Firestore**. The legacy `events.jsonl` file is no longer written.

### Collections

| Collection                  | Doc ID                                | Notes                                                                  |
| --------------------------- | ------------------------------------- | ---------------------------------------------------------------------- |
| `calls`                     | Twilio `CallSid`                      | One doc per call; `events/` subcollection holds the per-call timeline. |
| `calls/{sid}/events`        | auto-id                               | Append-only `CallEvent` log (started, transferDecided, smsLinkSent…).  |
| `callers`                   | E.164 phone (`+13125550123`)          | `callCount` is incremented transactionally on each new call.           |
| `messages`                  | auto-id                               | Inbound SMS + owner replies; `handled` flag drives the unhandled list. |
| `ownerOverrides`            | `singleton`                           | Single doc holding the active transfer policy override.                |

### Local development (Firestore emulator)

```bash
brew install firebase-cli
brew install openjdk@17        # the emulator's Java runtime
firebase emulators:start --only firestore
```

Tests pick up `FIRESTORE_EMULATOR_HOST` automatically — no service-account JSON needed locally. The session-scoped pytest fixture in `api/tests/conftest.py` clears the emulator between tests.

### Production credentials

The API resolves credentials in this order:

1. `FIRESTORE_EMULATOR_HOST` set → use the emulator (no creds).
2. `FIREBASE_SERVICE_ACCOUNT_PATH` points at a readable JSON file → load it.
3. Otherwise → fall back to ambient ADC (Cloud Run, GCE, Workload Identity).

For Docker / docker-compose, set `FIREBASE_SERVICE_ACCOUNT_HOST_PATH` on the host; it's bind-mounted read-only into the api container at `/run/firebase/sa.json`. For Fly.io, store the JSON as a multiline secret:

```bash
fly secrets set FIREBASE_SERVICE_ACCOUNT_JSON="$(cat firebase-admin.json)"
# then in the container, write it to /run/firebase/sa.json at boot
```

`FIREBASE_PROJECT_ID` is always required.

### Backfill from legacy JSONL

If you have a pre-Firestore `events.jsonl`, replay it once:

```bash
cd api
.venv/bin/python -m scripts.backfill_events_jsonl ./events.jsonl --dry-run    # preview
.venv/bin/python -m scripts.backfill_events_jsonl ./events.jsonl              # write
```

The script is idempotent (uses deterministic doc IDs derived from call SID + event timestamp), so re-running won't duplicate data.

## Architecture

N-tier (Hexagonal) — dependencies flow inward only:

```
api/                  Presentation layer (FastAPI routes)
  routes/             One file per resource
  dependencies.py     Auth, DI, app state
  app_factory.py      build_app(deps) -> FastAPI
services/             Business logic
domain/               Pydantic models — zero deps
infrastructure/       Adapters: config, logger, cache, Square SDK,
                      tenant registry, JSONL event log
```

## API endpoints (Plan 1)

All `/api/*` endpoints require `X-Tools-Auth: $TOOLS_SHARED_SECRET`. Tenant is selected via `?tenant=<slug>`.

### Voice-agent endpoints (no IDs ever — system resolves "today's pickup" automatically)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/pickup/today` | Today's active pickup spot — name, address, hours, speakable summary |
| GET | `/api/menu/search?q=` | Menu search via Square Catalog |
| GET | `/api/specials` | Today's specials (from tenant config) |
| POST | `/api/messages` | Record a take-message; appends to JSONL (Twilio SMS in Plan 2) |
| POST | `/api/transfers` | Decide transfer-vs-take-message based on owner-available hours |
| POST | `/api/calls/{sid}/event` | Generic call-event log append |

### Admin-panel endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/locations` | List Square locations (for the dropdown) |
| GET | `/api/locations/{id}/hours/today` | Per-location today's hours (debug / admin views) |
| GET | `/api/locations/{id}/address` | Per-location address |
| POST | `/api/admin/pickup` | Set today's active pickup spot |

### System

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness (no auth) |
| POST | `/api/webhooks/square` | Square webhook (HMAC-verified) — invalidates cache |

## Project status

| Plan | Status | What it covers |
|---|---|---|
| **Plan 1** — FastAPI + Square API | ✅ Shipped (75 tests) | Locations, hours, address, menu, specials, pickup, take-message + transfer skeletons |
| **Plan 2** — Pipecat voice agent + Twilio | ✅ Shipped (66 tests) | Real Twilio SMS, live-call transfer, Pipecat pipeline (Deepgram + Groq + Cartesia), system prompt, owner-transfer shortcut, 90s auto-transfer, slim menu output |
| **Deploy + security baseline** | 🚧 In progress — see [docs/superpowers/plans/2026-05-13-deploy-and-security-baseline.md](docs/superpowers/plans/2026-05-13-deploy-and-security-baseline.md) | Dockerize both services, Twilio signature validation enforced on all webhook routes, production-gate boot check, fly.toml configs. Hosting target TBD. |

## Hosting status

The agent is **not yet deployed** to a public host. Both services are fully Dockerized and have `fly.toml` configs ready. Hosting decision is pending — Fly.io is the leading candidate ($0–7/mo, no cold starts), but any Docker-capable host will work (Cloud Run, Render, Hetzner). The `deploy/` directory contains unused Caddy + systemd artifacts from an earlier Oracle Cloud attempt that didn't pan out.
