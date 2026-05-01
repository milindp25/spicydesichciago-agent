# Spicy Desi AI Voice Agent — Design

**Date:** 2026-05-01
**Status:** Draft, pending approval
**Primary tenant:** Spicy Desi Chicago (restaurant)
**Architecture goal:** Single-tenant launch, multi-tenant ready

## Problem

Spicy Desi Chicago wants an AI phone agent that handles inbound customer calls — answers common questions (hours, location, menu, specials, dietary, parking) and only transfers to the owner when the caller explicitly asks for a human or the agent can't confidently answer. Goal: cut interruptions to the owner while keeping a polished customer experience, and keep the door open to reuse the system for other businesses later.

Cost target: **<$10/month** ongoing at expected restaurant volume (~1,500–3,000 min/mo). Achieved by self-hosting the orchestrator on Oracle Cloud free ARM, using Groq's free LLM tier, and paying only for telephony and TTS.

## Non-goals (v1)

- Outbound calling
- Online order taking with payment
- Live reservation booking into a system like OpenTable (we capture the request, owner confirms by callback)
- Custom analytics dashboard (Twilio + log files for v1)

## Stack

Adopted from a prior Pipecat-based design that's already proven for a single-restaurant deployment:

| Layer | Choice | Why |
|---|---|---|
| Telephony | **Twilio Voice + Media Streams** | Cheapest for inbound at this volume; mature WebSocket bridge; fallback-destination support for outages |
| Orchestrator | **Pipecat** (Python) | Open-source voice-agent framework; built-in Twilio + Deepgram + Groq + Cartesia integrations; barge-in / endpointing handled |
| VAD | **Silero VAD** | Standard with Pipecat |
| STT | **Deepgram Nova-3** (`language=multi`) | Best multilingual accuracy incl. Hindi, English; $200 free credit; cheap after |
| LLM | **Groq Llama 3.3 70B Versatile** (free tier) | 1,000 RPD free, sub-second latency, strong tool-calling. Fallback to 3.1 8B Instant if rate-limited. |
| TTS | **Cartesia Sonic-2** (multilingual) | Good Hindi/English code-switching; cheaper than ElevenLabs; reasonable Telugu (validate before launch) |
| Backend (tools) | **Existing Express API** on Oracle Cloud (or fresh Node + TS Hono if none exists yet) | Square wrappers, SQLite for logs, REST tool endpoints |
| Hosting | **Oracle Cloud Free Tier ARM** (Ampere A1, 4 cores / 24 GB) | $0/mo, plenty for Pipecat + Express + SQLite |
| TLS / reverse proxy | **Caddy** | Auto Let's Encrypt; Twilio requires `wss://` |
| Process manager | **systemd** | One unit per service, auto-restart |
| SMS | **Twilio SMS** | Owner notifications, caller confirmations |
| Database | **SQLite** (single file on the box) | Call logs, transcripts, messages — sub-restaurant volume doesn't need anything bigger |
| Menu / hours data | **Square Catalog & Locations API** | Single source of truth — owner edits in Square dashboard |

## Architecture

```
Caller
  │
  ▼
Twilio phone number (provisioned new)
  │
  ▼ Webhook: POST /twilio/inbound (TwiML response)
  ▼ Media stream: WSS /twilio/stream
  │
  ▼
┌──────────────────────────────────────────────────┐
│ Oracle Cloud ARM box (free tier)                 │
│                                                  │
│   Pipecat process (Python, port 8000)            │
│     Silero VAD                                   │
│       → Deepgram STT (multi)                     │
│       → Groq Llama 3.3 70B  (with tool calls)    │
│       → Cartesia TTS                             │
│       → back to Twilio                           │
│                                                  │
│   Express API (Node, port 3000)                  │
│     /api/locations           (Square)            │
│     /api/locations/:id/hours/today (Square)      │
│     /api/locations/:id/menu/search (Square)      │
│     /api/locations/:id/specials (Square)         │
│     /api/messages   (POST — saves + SMS owner)   │
│     /api/transfers  (POST — initiates Twilio dial)│
│     /api/calls/:sid (transcript logging)         │
│                                                  │
│   SQLite file (calls, transcripts, messages)     │
│                                                  │
│   Caddy → TLS → both services                    │
│   systemd → restart on crash                     │
└──────────────────────────────────────────────────┘
                          │
                          ▼
              Square API (Catalog, Locations)
              Twilio REST (transfer dial, SMS)
```

## Repository layout

```
spicydesichciago-agent/
  agent/                         # Pipecat (Python)
    server.py
    bot.py                       # pipeline + tool-call handlers
    tools.py                     # HTTP client → Express API
    prompts/
      system.md                  # personality, escalation rules, language switching
    requirements.txt
    .env.example
  api/                           # Express API (Node + TS)
    src/
      routes/
        locations.ts
        menu.ts
        specials.ts
        messages.ts
        transfers.ts
        calls.ts
      square/
        client.ts                # Square SDK wrapper + cache
        cache.ts                 # in-memory TTL cache
      twilio/
        sms.ts
        transfer.ts              # REST /Calls/{Sid}/Recordings (transfer)
      db/
        schema.sql
        migrations/
      auth.ts                    # shared-secret auth for tool calls
    package.json
    .env.example
  configs/
    spicy-desi/
      tenant.json                # owner_phone, owner_hours, square_merchant_id, languages, location_overrides
      faq.md                     # parking, allergens, payment methods, dress code
      location-notes.md          # per-location parking / cross-street notes
  scripts/
    sync-tenant.ts               # uploads system prompt + faq into agent runtime
    deploy-oracle.sh             # rsync + systemd reload
  deploy/
    voice-agent.service          # systemd unit for Pipecat
    voice-api.service            # systemd unit for Express
    Caddyfile
  docs/
    superpowers/specs/
  README.md
```

## Components

### 1. Pipecat agent (`agent/`)

A Python service that owns the voice loop.

- **`server.py`** — minimal HTTP + WebSocket server.
  - `POST /twilio/inbound` returns TwiML that connects the call to the Media Stream.
  - `WSS /twilio/stream` runs the Pipecat pipeline for the duration of the call.
- **`bot.py`** — defines the Pipecat pipeline:
  - Silero VAD → Deepgram (Nova-3, `language=multi`) → Groq (Llama 3.3 70B with tool calls) → Cartesia → Twilio out.
  - System prompt loaded from `prompts/system.md` plus the tenant config (FAQ, location notes, owner hours).
  - Tool-call handlers in `tools.py` — every tool just HTTP POSTs to the Express API with a shared-secret header.
- **System prompt rules** (excerpt):
  - Greet in English; detect caller language; switch to Hindi or Telugu if caller speaks it.
  - Ask which location the caller is asking about, if more than one is returned by `list_locations`. Skip if there's only one.
  - Use tools for menu, hours, address, specials. Never invent an item or price.
  - Escalate (`transfer_to_owner` or `take_message`) on: explicit human request, complaint, refund, allergic reaction, lost item, large catering (>$200 or >20 people), press inquiry, or any question the agent can't answer with high confidence.
  - During hours when owner is available → call `transfer_to_owner`. Outside those hours → call `take_message`.

### 2. Express API (`api/`)

A small Node + TypeScript Express service. Already exists per prior conversation; we extend it with the endpoints below. If it doesn't exist yet, scaffold one with the same surface.

All endpoints require an `X-Tools-Auth` header matching `TOOLS_SHARED_SECRET`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/locations` | List Square locations: `[{location_id, name, address, has_hours_today}]` |
| GET | `/api/locations/:id/hours/today` | `{open, close, status: "open"|"closed"|"closing_soon", next_open?}` |
| GET | `/api/locations/:id/address` | `{formatted, lat, lng, parking_note}` |
| GET | `/api/locations/:id/menu/search?q=...` | `[{name, price, description, category, dietary_tags}]` |
| GET | `/api/locations/:id/specials` | Items in the "Specials" category for that location |
| POST | `/api/messages` | Body: `{caller_name, callback_number, reason, language, location_id, call_sid}`. Saves to DB, sends SMS to owner. |
| POST | `/api/transfers` | Body: `{call_sid, reason, location_id}`. Validates owner-available hours; if OK, initiates Twilio REST `POST /2010-04-01/Accounts/{Sid}/Calls/{CallSid}.json` to redirect the live call to the owner's cell. If outside hours, returns `{action: "take_message"}` so the agent falls back. |
| POST | `/api/calls/:sid` | Append transcript chunks; updates final summary on call-end. |
| POST | `/api/webhooks/square` | Square `catalog.version.updated` → invalidates the in-memory catalog cache. |

**Square caching:**
- Catalog: 5-min TTL in-memory, invalidated by Square webhook.
- Locations: 1-hour TTL in-memory.
- On Square error, serve last cached value and log; surface to the agent only if cache is also empty.

**Auth:**
- Twilio webhooks: verify `X-Twilio-Signature`.
- Internal tool calls from agent → API: `X-Tools-Auth: $TOOLS_SHARED_SECRET`.
- Square webhooks: verify HMAC signature with the Square notification key.

### 3. Configuration (`configs/<tenant-slug>/`)

Square is the source of truth for menu and hours, so the config is intentionally thin:

```
configs/spicy-desi/
  ├── tenant.json
  ├── faq.md
  └── location-notes.md
```

`tenant.json` shape:
```json
{
  "name": "Spicy Desi",
  "twilio_number": "+1XXXXXXXXXX",
  "owner_phone": "+1YYYYYYYYYY",
  "owner_available": {
    "tz": "America/Chicago",
    "weekly": { "mon": ["11:00", "21:30"], "...": "..." }
  },
  "square_merchant_id": "...",
  "languages": ["en", "hi", "te"],
  "location_overrides": {
    "<square_location_id>": { "parking_note": "Free lot in back" }
  }
}
```

A tiny `npm run sync:tenant -- spicy-desi` script reloads the system prompt + FAQ in the running Pipecat process via a signal or a simple HTTP endpoint (`POST /admin/reload`). Square data is never synced — agent fetches it live.

### 4. Storage (SQLite on the box)

Tables:
- `calls(call_sid PK, tenant_id, started_at, ended_at, language, location_id, outcome)`
- `transcripts(id PK, call_sid FK, role, text, ts)`
- `messages(id PK, call_sid FK, caller_name, callback_number, reason, sent_to_owner_at)`
- `transfers(id PK, call_sid FK, initiated_at, reason, succeeded)`

Daily SQLite backup to a separate directory; weekly backup uploaded to S3-compatible storage (Cloudflare R2 free tier) — small and cheap insurance.

### 5. Multi-tenancy hook

Even though v1 ships only Spicy Desi:
- Each Twilio phone number maps to one `tenant_id` (lookup table in `configs/index.json`).
- Pipecat agent reads `tenant_id` from the inbound webhook's `To` number, loads that tenant's prompt + FAQ + Square credentials.
- Express API endpoints take `tenant_id` from the auth context (or path param) so no per-tenant fork is needed.

## Call flow (golden path)

1. Caller dials Spicy Desi number → Twilio webhooks `POST /twilio/inbound`.
2. TwiML response opens a Media Stream to `WSS /twilio/stream`.
3. Pipecat pipeline starts; greets caller in English ("Thank you for calling Spicy Desi…").
4. Deepgram detects language; LLM continues in Hindi/Telugu/English.
5. **Location selection:** agent calls `list_locations`. If >1, asks "Which location are you calling about?" and stores `location_id` for the rest of the call. If 1, uses it silently.
6. Agent answers the caller's question by calling the relevant tool:
   - "Are you open?" → `get_hours_today`
   - "Where are you?" → `get_address`
   - "Do you have X?" / "How much is X?" / "Is X vegan?" → `search_menu`
   - "Specials today?" → `get_specials`
   - Parking, dress, payment, allergens → answered from `faq.md` directly
7. Escalation:
   - Within owner-available hours + escalation trigger → `transfer_to_owner` → Express API redirects the live call via Twilio REST to the owner's cell. If owner doesn't pick up in 30s, the call returns to the agent which then runs `take_message`.
   - Outside hours → agent says "the owner isn't available right now, can I take a message?" → `take_message` → SMS to owner + (optional) SMS confirmation to caller.
8. Pipecat streams transcript chunks to `POST /api/calls/:sid` as the call progresses; on call-end, writes a final summary row.

## Confidence-and-escalation rules

In the system prompt, the agent must escalate when:
- Caller explicitly asks for a human, owner, manager, or specific person.
- Caller mentions: complaint, refund, sick, allergic reaction, lost item, large catering (>$200 or >20 people), press/media inquiry, lost-and-found, accessibility issue.
- A `search_menu` returns no match for an item the caller asks about — agent says "I don't see that on our menu, let me have someone call you back" instead of guessing.
- The caller's question is unclear after one clarification attempt.

## Languages

- **English:** Deepgram Nova-3 multilingual + Cartesia English voice.
- **Hindi:** Deepgram Nova-3 multilingual + Cartesia multilingual voice (validated in test calls).
- **Telugu:** Deepgram Nova-3 supports Telugu in `language=multi`. Cartesia's Telugu quality is the unknown — we test with native speakers in pre-launch. If poor, we either (a) fall back to Hindi+English only and warm-route Telugu callers to the owner, or (b) pay Azure Neural TTS only for Telugu (~$0.016/min on those calls).

## Hours-aware transfer behavior (gap from prior design)

The prior design noted `transfer_to_human` was a stub. We implement it in `api/src/twilio/transfer.ts` using Twilio REST: `POST /2010-04-01/Accounts/{Sid}/Calls/{CallSid}.json` with new TwiML that `<Dial>`s the owner's cell, with `timeout=25` and `action=…/api/calls/:sid/transfer-fallback`. If the owner doesn't answer, the fallback URL routes back into the agent, which calls `take_message` automatically.

`tenant.owner_available` is checked first — outside those hours, the API returns `{action: "take_message"}` and the agent never even attempts the transfer.

## SMS confirmation to caller (gap from prior design)

After `take_message` succeeds, the API optionally sends an SMS to the caller's number: *"Thanks for calling Spicy Desi. We've got your message about [reason] and will call you back from <owner_phone>."* Behind a `tenant.json` flag (`sms_confirmation_to_caller: true|false`) so this can be disabled per business.

## Post-call transcript logging (gap from prior design)

Pipecat emits transcript frames during the call; we POST chunks to `/api/calls/:sid` every ~5s, and on call-end the API writes an `outcome` summary by calling Groq once with the full transcript and a fixed prompt: *"Summarize this call in one sentence and classify outcome as one of: answered, transferred, message_taken, dropped."*

## Cost estimate

At Spicy Desi expected volume (~30 calls/day × ~2 min average = ~1,800 min/month):

| Line item | $/month | Notes |
|---|---:|---|
| Twilio number | $1.15 | Fixed |
| Twilio inbound | ~$15 | $0.0085/min × 1,800 |
| Twilio SMS (10/day) | ~$2 | $0.008/SMS |
| Groq LLM | $0 | Within free tier (1,000 RPD; we're well under) |
| Deepgram STT | ~$8 | After $200 credit; $0.0043/min × 1,800 |
| Cartesia TTS | ~$25 | ~$0.014/min effective |
| Oracle ARM | $0 | Free tier |
| Cloudflare R2 backups | $0 | Free tier |
| Square API | $0 | Free with merchant account |

**Estimated total: ~$50/month at 1,800 min** — driven mostly by per-minute usage. At lower volume (1,000 min/mo) it drops to ~$25/month. At higher volume (3,000 min/mo) ~$80/month.

The prior design's "$2–5/month" estimate was for ~110 min/month. Our restaurant case is ~16× that volume.

If even this is too much, the largest remaining lever is **Cartesia → self-hosted Coqui XTTS-v2 on the same Oracle box** (Ampere A1 has enough RAM, but Telugu quality drops). That cuts ~$25/month at the cost of voice quality. Documented as a Phase 7 optimization, not v1.

## Risks

1. **Telugu TTS quality on Cartesia** — mitigation: tested before launch with native speakers; fall back to Hindi/English-only or Azure Neural TTS for Telugu turns.
2. **Groq free-tier rate limits** — mitigation: 1,000 RPD is plenty for restaurant volume, but we add a circuit breaker that switches to Llama 3.1 8B Instant on rate-limit errors and alerts.
3. **Oracle ARM free-tier reclamation** — Oracle has been known to reclaim idle free instances; mitigation: a cron job that pings the API every 5 minutes keeps it active. Daily SQLite backup to R2 means a 24-hour worst case if reclaimed.
4. **Tool-calling reliability on Llama 3.1 8B** — design uses 3.3 70B by default; 8B is fallback. We log tool-call success rate per call.
5. **Square API outage** — 5-min cache + last-known fallback; if cache empty, agent says "I'm having trouble looking that up right now, can I have the owner call you back?" → `take_message`.
6. **Transcript PII** — call recordings contain customer phone numbers and names. SQLite file is on the Oracle box behind Caddy + auth; backups encrypted at rest in R2. 90-day retention, then auto-delete.
7. **Cold-start on Pipecat after restart** — first call after restart can take ~3s extra. systemd `Restart=always` minimizes downtime; we accept the cold-start cost.

## Open questions for the user

1. Owner's cell number + the `owner_available` weekly window for live transfer?
2. Existing accounts: Twilio? Groq? Deepgram? Cartesia? Square OAuth token? Oracle Cloud free-tier instance? (Check what we already have vs need to provision.)
3. Does the existing Express API mentioned in the prior design still exist somewhere we can extend, or do we scaffold a fresh one in `api/`?
4. How many Spicy Desi locations are in Square right now?
5. Is "Specials" already a category in Square Catalog, or do we set one up so `get_specials` has data?
6. SMS confirmation back to caller — on or off?
7. Domain for Caddy/TLS? (e.g., `voice.spicydesi.com`)

## Implementation phases (preview — actual plan comes from writing-plans next)

1. **Phase 0 — accounts + provisioning:** Twilio number, Groq key, Deepgram key (claim free credit), Cartesia key, Square OAuth token, Oracle Cloud ARM instance, domain DNS.
2. **Phase 1 — Express API skeleton:** Hono or Express on Oracle, SQLite schema, Twilio signature verification, shared-secret auth, deploy with systemd + Caddy.
3. **Phase 2 — Square integration:** Locations + Catalog clients with caching; webhook for catalog invalidation; `/api/locations`, `/api/locations/:id/hours/today`, `/api/locations/:id/menu/search`, `/api/locations/:id/specials`, `/api/locations/:id/address`.
4. **Phase 3 — Pipecat agent:** scaffold from a Pipecat Twilio template; wire Deepgram/Groq/Cartesia; system prompt loader; tools client.
5. **Phase 4 — escalation flows:** `take_message` (with SMS to owner + optional caller SMS), `transfer_to_owner` (real Twilio REST redirect, hours-aware, fallback to take_message).
6. **Phase 5 — transcript logging + summary:** chunk POST to `/api/calls/:sid`; end-of-call Groq summary.
7. **Phase 6 — multilingual tuning:** test EN/HI/TE on real calls with native speakers; tweak prompt + voice; decide Telugu fate.
8. **Phase 7 — soft launch:** point Spicy Desi number at the agent; owner's cell as Twilio fallback destination if the agent box is down; monitor first 50 calls; iterate.
