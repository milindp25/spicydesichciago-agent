# Spicy Desi Voice Agent

AI phone agent for Spicy Desi Chicago. Pipecat + Groq + Cartesia voice loop on top of a Hono/TypeScript API backed by Square Catalog & Locations.

## Repo layout

- `api/` — TypeScript API the voice agent calls (Plan 1)
- `agent/` — Pipecat voice agent (Plan 2)
- `configs/<tenant>/` — per-tenant config and FAQ
- `deploy/` — systemd + Caddy for Oracle Cloud
- `docs/superpowers/` — design specs and implementation plans

## Quick start (API)

```
cd api
cp .env.example .env  # fill in keys
npm install
npm run dev
```

See `docs/superpowers/plans/` for implementation plans.
