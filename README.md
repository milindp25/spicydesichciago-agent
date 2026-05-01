# Spicy Desi Voice Agent

AI phone agent for Spicy Desi Chicago. Pipecat + Groq + Cartesia voice loop on top of a FastAPI/Python service backed by Square Catalog & Locations.

## Repo layout

- `api/` — FastAPI Python service the voice agent calls (Plan 1, **shipped**)
- `agent/` — Pipecat voice agent (Plan 2, future)
- `configs/<tenant>/` — per-tenant config and FAQ
- `deploy/` — systemd + Caddy for Oracle Cloud (Plan 3, future)
- `docs/superpowers/specs/` — design specs
- `docs/superpowers/plans/` — implementation plans

## Quick start (API)

```
cd api
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill in keys
uvicorn app.main:app --reload --port 8080
```

Then in a second terminal:

```
SECRET=$(python3 -c 'print("x"*32)')
curl http://localhost:8080/healthz
curl -H "X-Tools-Auth: $SECRET" "http://localhost:8080/api/locations?tenant=spicy-desi"
```

## Tests

```
cd api && source .venv/bin/activate
pytest
```

Currently 48 tests (28 unit + 20 integration), all hermetic — no live Square calls.

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

## What's deferred

- **Plan 2:** Pipecat voice agent + real Twilio SMS in `/api/messages` + real Twilio REST live-call redirect in `/api/transfers` + Hindi/Telugu Cartesia tuning
- **Plan 3:** Oracle Cloud deployment (systemd, Caddy, runbook), R2 backups of `data/events.jsonl`, end-to-end multilingual call testing, soft launch
