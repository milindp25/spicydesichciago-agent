# Plan 1 — Part 3 (Tasks 13–20)

> Continues `2026-05-01-plan-1-foundation-and-square-api-part-2.md`. Same conventions: TDD, every step has runnable code, every task ends with a commit.

---

## Task 13: GET /api/locations/:id/address route

**Files:**
- Create: `api/src/routes/address.ts`
- Create: `api/test/address.test.ts`
- Modify: `api/src/server.ts`

- [ ] **Step 1: Write the failing test**

Create `api/test/address.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { buildTestApp } from "./helpers/app.ts";

const SAMPLE = [
  {
    id: "L1",
    name: "Loop",
    address: { addressLine1: "111 W Madison", locality: "Chicago" },
    coordinates: { latitude: 41.881, longitude: -87.631 },
    businessHours: { periods: [] },
  },
];

describe("GET /api/locations/:id/address", () => {
  it("returns formatted address + coords", async () => {
    const { app, secret } = buildTestApp({ locations: SAMPLE });
    const r = await app.request("/api/locations/L1/address?tenant=spicy-desi", {
      headers: { "X-Tools-Auth": secret },
    });
    expect(r.status).toBe(200);
    const body = (await r.json()) as { formatted: string; lat: number };
    expect(body.formatted).toContain("111 W Madison");
    expect(body.lat).toBeCloseTo(41.881);
  });

  it("returns 404 for unknown location", async () => {
    const { app, secret } = buildTestApp({ locations: SAMPLE });
    const r = await app.request("/api/locations/Lnope/address?tenant=spicy-desi", {
      headers: { "X-Tools-Auth": secret },
    });
    expect(r.status).toBe(404);
  });
});
```

- [ ] **Step 2: Implement `api/src/routes/address.ts`**

```ts
import { Hono } from "hono";
import type { AppDeps } from "../server.ts";

export const addressRouter = new Hono<{ Variables: { deps: AppDeps } }>();

addressRouter.get("/api/locations/:id/address", async (c) => {
  const tenant = c.req.query("tenant");
  if (!tenant) return c.json({ error: "tenant query param required" }, 400);
  const deps = c.get("deps");
  if (!deps.tenants.tenants[tenant]) return c.json({ error: "tenant not found" }, 404);
  try {
    const addr = await deps.locationsByTenant(tenant).getAddress(c.req.param("id"));
    return c.json(addr);
  } catch (e) {
    if (e instanceof Error && e.message.startsWith("location not found")) {
      return c.json({ error: e.message }, 404);
    }
    throw e;
  }
});
```

- [ ] **Step 3: Wire in `api/src/server.ts`**

```ts
import { addressRouter } from "./routes/address.ts";
// ...
  app.route("/", addressRouter);
```

- [ ] **Step 4: Run tests**

```bash
cd api && npm test -- address.test
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/routes/address.ts api/src/server.ts api/test/address.test.ts
git commit -m "feat(api): GET address route"
```

---

## Task 14: GET menu/search route

**Files:**
- Create: `api/src/routes/menu.ts`
- Create: `api/test/menu.test.ts`
- Modify: `api/src/server.ts`

- [ ] **Step 1: Write the failing test**

Create `api/test/menu.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { buildTestApp } from "./helpers/app.ts";

const ITEMS = [
  {
    id: "I1",
    type: "ITEM",
    itemData: {
      name: "Chicken Tikka Masala",
      description: "creamy tomato",
      categories: [{ id: "MAINS" }],
      variations: [{ id: "V1", itemVariationData: { priceMoney: { amount: 1899, currency: "USD" } } }],
    },
  },
];

describe("GET /api/locations/:id/menu/search", () => {
  it("returns matching items", async () => {
    const { app, secret } = buildTestApp({ catalogItems: ITEMS });
    const r = await app.request(
      "/api/locations/L1/menu/search?tenant=spicy-desi&q=tikka",
      { headers: { "X-Tools-Auth": secret } }
    );
    expect(r.status).toBe(200);
    const body = (await r.json()) as { items: any[] };
    expect(body.items[0].name).toBe("Chicken Tikka Masala");
  });

  it("requires q param", async () => {
    const { app, secret } = buildTestApp({ catalogItems: ITEMS });
    const r = await app.request(
      "/api/locations/L1/menu/search?tenant=spicy-desi",
      { headers: { "X-Tools-Auth": secret } }
    );
    expect(r.status).toBe(400);
  });
});
```

- [ ] **Step 2: Implement `api/src/routes/menu.ts`**

```ts
import { Hono } from "hono";
import type { AppDeps } from "../server.ts";

export const menuRouter = new Hono<{ Variables: { deps: AppDeps } }>();

menuRouter.get("/api/locations/:id/menu/search", async (c) => {
  const tenant = c.req.query("tenant");
  const q = c.req.query("q");
  if (!tenant) return c.json({ error: "tenant query param required" }, 400);
  if (!q) return c.json({ error: "q query param required" }, 400);
  const deps = c.get("deps");
  if (!deps.tenants.tenants[tenant]) return c.json({ error: "tenant not found" }, 404);
  const svc = deps.catalogByTenant(tenant);
  const items = await svc.searchMenu(q);
  return c.json({ items });
});
```

- [ ] **Step 3: Wire in `api/src/server.ts`**

```ts
import { menuRouter } from "./routes/menu.ts";
// ...
  app.route("/", menuRouter);
```

- [ ] **Step 4: Run tests**

```bash
cd api && npm test -- menu.test
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/routes/menu.ts api/src/server.ts api/test/menu.test.ts
git commit -m "feat(api): GET menu search route"
```

---

## Task 15: GET specials route

**Files:**
- Create: `api/src/routes/specials.ts`
- Create: `api/test/specials.test.ts`
- Modify: `api/src/server.ts`

- [ ] **Step 1: Write the failing test**

Create `api/test/specials.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { buildTestApp } from "./helpers/app.ts";

const ITEMS = [
  {
    id: "I1",
    type: "ITEM",
    itemData: {
      name: "Mango Lassi",
      description: "",
      categories: [{ id: "SPECIALS" }],
      variations: [{ id: "V1", itemVariationData: { priceMoney: { amount: 499, currency: "USD" } } }],
    },
  },
];

describe("GET /api/locations/:id/specials", () => {
  it("returns specials", async () => {
    const { app, secret } = buildTestApp({ catalogItems: ITEMS });
    const r = await app.request(
      "/api/locations/L1/specials?tenant=spicy-desi",
      { headers: { "X-Tools-Auth": secret } }
    );
    expect(r.status).toBe(200);
    const body = (await r.json()) as { items: any[] };
    expect(body.items[0].name).toBe("Mango Lassi");
  });
});
```

- [ ] **Step 2: Implement `api/src/routes/specials.ts`**

```ts
import { Hono } from "hono";
import type { AppDeps } from "../server.ts";

export const specialsRouter = new Hono<{ Variables: { deps: AppDeps } }>();

specialsRouter.get("/api/locations/:id/specials", async (c) => {
  const tenant = c.req.query("tenant");
  if (!tenant) return c.json({ error: "tenant query param required" }, 400);
  const deps = c.get("deps");
  if (!deps.tenants.tenants[tenant]) return c.json({ error: "tenant not found" }, 404);
  const svc = deps.catalogByTenant(tenant);
  const items = await svc.getSpecials();
  return c.json({ items });
});
```

- [ ] **Step 3: Wire in `api/src/server.ts`**

```ts
import { specialsRouter } from "./routes/specials.ts";
// ...
  app.route("/", specialsRouter);
```

- [ ] **Step 4: Run tests**

```bash
cd api && npm test -- specials.test
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/routes/specials.ts api/src/server.ts api/test/specials.test.ts
git commit -m "feat(api): GET specials route"
```

---

## Task 16: Skeleton routes — messages, transfers, calls

These are placeholders that record the request and return a stub response. Plan 2 fills in real Twilio + SMS logic.

**Files:**
- Create: `api/src/routes/messages.ts`
- Create: `api/src/routes/transfers.ts`
- Create: `api/src/routes/calls.ts`
- Create: `api/test/skeleton_routes.test.ts`
- Modify: `api/src/server.ts`

- [ ] **Step 1: Write the failing test**

Create `api/test/skeleton_routes.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { buildTestApp } from "./helpers/app.ts";

describe("skeleton routes", () => {
  it("POST /api/messages records the message and returns 202", async () => {
    const { app, secret, deps } = buildTestApp();
    const r = await app.request("/api/messages", {
      method: "POST",
      headers: { "X-Tools-Auth": secret, "Content-Type": "application/json" },
      body: JSON.stringify({
        call_sid: "CA1",
        caller_name: "Asha",
        callback_number: "+15555550123",
        reason: "wants catering quote",
        language: "en",
        location_id: "L1",
      }),
    });
    expect(r.status).toBe(202);
    const row = deps.db.prepare("SELECT * FROM messages WHERE call_sid = ?").get("CA1") as
      | { reason: string }
      | undefined;
    expect(row?.reason).toBe("wants catering quote");
  });

  it("POST /api/transfers returns take_message action when outside owner-available hours", async () => {
    const { app, secret } = buildTestApp();
    // Sunday 04:00 Chicago — outside the test config's mon-only window
    const r = await app.request("/api/transfers?now=2026-05-03T09:00:00Z", {
      method: "POST",
      headers: { "X-Tools-Auth": secret, "Content-Type": "application/json" },
      body: JSON.stringify({ call_sid: "CA1", reason: "owner please", location_id: "L1" }),
    });
    expect(r.status).toBe(200);
    const body = (await r.json()) as { action: string };
    expect(body.action).toBe("take_message");
  });

  it("POST /api/calls/:sid/transcript appends a transcript row", async () => {
    const { app, secret, deps } = buildTestApp();
    deps.db
      .prepare("INSERT INTO calls (call_sid, tenant_id, started_at) VALUES (?, ?, ?)")
      .run("CA1", "spicy-desi", Date.now());
    const r = await app.request("/api/calls/CA1/transcript", {
      method: "POST",
      headers: { "X-Tools-Auth": secret, "Content-Type": "application/json" },
      body: JSON.stringify({ chunks: [{ role: "user", text: "hello", ts: 1 }] }),
    });
    expect(r.status).toBe(202);
    const row = deps.db.prepare("SELECT * FROM transcripts WHERE call_sid = ?").get("CA1") as
      | { text: string }
      | undefined;
    expect(row?.text).toBe("hello");
  });
});
```

- [ ] **Step 2: Implement `api/src/routes/messages.ts`**

```ts
import { Hono } from "hono";
import { z } from "zod";
import type { AppDeps } from "../server.ts";

const bodySchema = z.object({
  call_sid: z.string(),
  caller_name: z.string().optional(),
  callback_number: z.string(),
  reason: z.string(),
  language: z.string().optional(),
  location_id: z.string().optional(),
});

export const messagesRouter = new Hono<{ Variables: { deps: AppDeps } }>();

messagesRouter.post("/api/messages", async (c) => {
  const json = await c.req.json().catch(() => null);
  const parsed = bodySchema.safeParse(json);
  if (!parsed.success) return c.json({ error: "invalid body", details: parsed.error.flatten() }, 400);
  const { db } = c.get("deps");
  const now = Date.now();

  db.prepare(
    "INSERT OR IGNORE INTO calls (call_sid, tenant_id, started_at) VALUES (?, ?, ?)"
  ).run(parsed.data.call_sid, "spicy-desi", now);

  db.prepare(
    `INSERT INTO messages
       (call_sid, caller_name, callback_number, reason, language, location_id, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)`
  ).run(
    parsed.data.call_sid,
    parsed.data.caller_name ?? null,
    parsed.data.callback_number,
    parsed.data.reason,
    parsed.data.language ?? null,
    parsed.data.location_id ?? null,
    now
  );
  return c.json({ ok: true, sms_sent: false }, 202);
});
```

- [ ] **Step 3: Implement `api/src/routes/transfers.ts`**

```ts
import { Hono } from "hono";
import { z } from "zod";
import type { AppDeps } from "../server.ts";

const bodySchema = z.object({
  call_sid: z.string(),
  reason: z.string().optional(),
  location_id: z.string().optional(),
});

export const transfersRouter = new Hono<{ Variables: { deps: AppDeps } }>();

transfersRouter.post("/api/transfers", async (c) => {
  const json = await c.req.json().catch(() => null);
  const parsed = bodySchema.safeParse(json);
  if (!parsed.success) return c.json({ error: "invalid body" }, 400);

  const deps = c.get("deps");
  const tenant = deps.tenants.tenants["spicy-desi"];
  if (!tenant) return c.json({ error: "tenant not found" }, 404);

  const nowOverride = c.req.query("now");
  const now = nowOverride ? new Date(nowOverride) : new Date();

  const tz = tenant.ownerAvailable.tz;
  const dayShort = new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short" })
    .format(now)
    .toLowerCase()
    .slice(0, 3) as keyof typeof tenant.ownerAvailable.weekly;
  const window = tenant.ownerAvailable.weekly[dayShort];

  const time = new Intl.DateTimeFormat("en-US", {
    timeZone: tz, hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(now);

  const inHours = window != null && time >= window[0] && time < window[1];
  if (!inHours) return c.json({ action: "take_message" });

  // Stub: actual Twilio REST redirect happens in Plan 2.
  deps.db.prepare(
    "INSERT OR IGNORE INTO calls (call_sid, tenant_id, started_at) VALUES (?, ?, ?)"
  ).run(parsed.data.call_sid, "spicy-desi", Date.now());
  deps.db.prepare(
    "INSERT INTO transfers (call_sid, initiated_at, reason, succeeded) VALUES (?, ?, ?, 0)"
  ).run(parsed.data.call_sid, Date.now(), parsed.data.reason ?? null);
  return c.json({ action: "transfer", target: tenant.ownerPhone, recorded: true });
});
```

- [ ] **Step 4: Implement `api/src/routes/calls.ts`**

```ts
import { Hono } from "hono";
import { z } from "zod";
import type { AppDeps } from "../server.ts";

const transcriptSchema = z.object({
  chunks: z.array(z.object({ role: z.string(), text: z.string(), ts: z.number() })),
});

export const callsRouter = new Hono<{ Variables: { deps: AppDeps } }>();

callsRouter.post("/api/calls/:sid/transcript", async (c) => {
  const json = await c.req.json().catch(() => null);
  const parsed = transcriptSchema.safeParse(json);
  if (!parsed.success) return c.json({ error: "invalid body" }, 400);
  const { db } = c.get("deps");
  const sid = c.req.param("sid");
  const stmt = db.prepare(
    "INSERT INTO transcripts (call_sid, role, text, ts) VALUES (?, ?, ?, ?)"
  );
  const insertMany = db.transaction((rows: typeof parsed.data.chunks) => {
    for (const r of rows) stmt.run(sid, r.role, r.text, r.ts);
  });
  insertMany(parsed.data.chunks);
  return c.json({ ok: true }, 202);
});
```

- [ ] **Step 5: Wire all three in `api/src/server.ts`**

```ts
import { messagesRouter } from "./routes/messages.ts";
import { transfersRouter } from "./routes/transfers.ts";
import { callsRouter } from "./routes/calls.ts";
// ...
  app.route("/", messagesRouter);
  app.route("/", transfersRouter);
  app.route("/", callsRouter);
```

- [ ] **Step 6: Run tests**

```bash
cd api && npm test -- skeleton_routes
```

Expected: PASS — 3 passing.

- [ ] **Step 7: Commit**

```bash
git add api/src/routes/messages.ts api/src/routes/transfers.ts api/src/routes/calls.ts \
        api/src/server.ts api/test/skeleton_routes.test.ts
git commit -m "feat(api): skeleton routes for messages, transfers, calls"
```

---

## Task 17: Square webhook — HMAC verify + cache invalidate

**Files:**
- Create: `api/src/routes/square_webhook.ts`
- Create: `api/test/square_webhook.test.ts`
- Modify: `api/src/server.ts`

- [ ] **Step 1: Write the failing test**

Create `api/test/square_webhook.test.ts`:

```ts
import { describe, it, expect, vi } from "vitest";
import { Hono } from "hono";
import { makeSquareWebhookRouter } from "../src/routes/square_webhook.ts";

describe("POST /api/webhooks/square", () => {
  it("rejects requests with a bad signature", async () => {
    const onInvalidate = vi.fn();
    const app = new Hono().route(
      "/",
      makeSquareWebhookRouter({ signatureKey: "key", onInvalidate, notifyUrl: "https://x" })
    );
    const r = await app.request("/api/webhooks/square", {
      method: "POST",
      headers: { "X-Square-Hmacsha256-Signature": "bad" },
      body: JSON.stringify({ type: "catalog.version.updated" }),
    });
    expect(r.status).toBe(401);
    expect(onInvalidate).not.toHaveBeenCalled();
  });

  it("invalidates cache on valid signature", async () => {
    const { createHmac } = await import("node:crypto");
    const body = JSON.stringify({ type: "catalog.version.updated" });
    const notifyUrl = "https://x.example.com/api/webhooks/square";
    const sig = createHmac("sha256", "key").update(notifyUrl + body).digest("base64");
    const onInvalidate = vi.fn();
    const app = new Hono().route(
      "/",
      makeSquareWebhookRouter({ signatureKey: "key", onInvalidate, notifyUrl })
    );
    const r = await app.request("/api/webhooks/square", {
      method: "POST",
      headers: { "X-Square-Hmacsha256-Signature": sig, "Content-Type": "application/json" },
      body,
    });
    expect(r.status).toBe(200);
    expect(onInvalidate).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Implement `api/src/routes/square_webhook.ts`**

```ts
import { Hono } from "hono";
import { createHmac, timingSafeEqual } from "node:crypto";

export type SquareWebhookDeps = {
  signatureKey: string;
  notifyUrl: string;
  onInvalidate: () => void;
};

export function makeSquareWebhookRouter(deps: SquareWebhookDeps) {
  const app = new Hono();
  app.post("/api/webhooks/square", async (c) => {
    const provided = c.req.header("X-Square-Hmacsha256-Signature") ?? "";
    const raw = await c.req.text();
    const expected = createHmac("sha256", deps.signatureKey)
      .update(deps.notifyUrl + raw)
      .digest("base64");
    const a = Buffer.from(provided);
    const b = Buffer.from(expected);
    if (a.length !== b.length || !timingSafeEqual(a, b)) {
      return c.json({ error: "invalid signature" }, 401);
    }
    deps.onInvalidate();
    return c.json({ ok: true });
  });
  return app;
}
```

- [ ] **Step 3: Mount the webhook in `api/src/server.ts`**

```ts
import { makeSquareWebhookRouter } from "./routes/square_webhook.ts";
// ...
  app.route("/", makeSquareWebhookRouter(deps.squareWebhook));
```

- [ ] **Step 4: Run tests**

```bash
cd api && npm test
```

Expected: full suite PASS.

- [ ] **Step 5: Commit**

```bash
git add api/src/routes/square_webhook.ts api/src/server.ts api/test/square_webhook.test.ts
git commit -m "feat(api): square webhook handler with HMAC verify + cache invalidate"
```

---

## Task 18: Process entrypoint

**Files:**
- Create: `api/src/index.ts`

- [ ] **Step 1: Implement `api/src/index.ts`**

```ts
import "dotenv/config";
import { serve } from "@hono/node-server";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { loadConfig } from "./config.ts";
import { makeLogger } from "./logger.ts";
import { loadTenants } from "./tenants.ts";
import { openDb } from "./db/client.ts";
import { TtlCache } from "./square/cache.ts";
import {
  makeSquareClient,
  locationsApiFromClient,
  catalogApiFromClient,
} from "./square/client.ts";
import { LocationsService } from "./square/locations.ts";
import { CatalogService } from "./square/catalog.ts";
import { buildApp } from "./server.ts";

const cfg = loadConfig();
const log = makeLogger(cfg.logLevel);

mkdirSync(dirname(cfg.dbPath), { recursive: true });
const db = openDb(cfg.dbPath);
const tenants = loadTenants(cfg.configsDir);

const squareClient = makeSquareClient(cfg.square);
const locApi = locationsApiFromClient(squareClient);
const catApi = catalogApiFromClient(squareClient);

const locationsCache = new TtlCache<any[]>(60 * 60 * 1000);
const specialsCache = new TtlCache<any[]>(5 * 60 * 1000);

const locationsService = new LocationsService(locApi, locationsCache);
const catalogService = new CatalogService(catApi, specialsCache, "SPECIALS");

const app = buildApp({
  toolsSharedSecret: cfg.toolsSharedSecret,
  tenants,
  db,
  locationsByTenant: () => locationsService,
  catalogByTenant: () => catalogService,
  squareWebhook: {
    signatureKey: cfg.square.webhookSignatureKey,
    notifyUrl: process.env.SQUARE_WEBHOOK_URL ?? "",
    onInvalidate: () => {
      log.info("square cache invalidated");
      locationsCache.clear();
      specialsCache.clear();
    },
  },
});

serve({ fetch: app.fetch, port: cfg.port }, (info) => {
  log.info({ port: info.port }, "api listening");
});
```

- [ ] **Step 2: Build to verify it typechecks**

```bash
cd api && npm run build
```

Expected: succeeds, `dist/index.js` produced.

- [ ] **Step 3: Smoke run with placeholder env**

```bash
cd api
TOOLS_SHARED_SECRET=$(node -e 'console.log("x".repeat(32))') \
DB_PATH=./data/voice-agent.db \
SQUARE_ACCESS_TOKEN=fake \
SQUARE_ENVIRONMENT=sandbox \
SQUARE_WEBHOOK_SIGNATURE_KEY=fake \
CONFIGS_DIR=../configs \
SQUARE_WEBHOOK_URL=https://example.com \
PORT=18080 \
NODE_ENV=development \
LOG_LEVEL=info \
node dist/index.js &
SERVER_PID=$!
sleep 1
curl -fsS http://localhost:18080/healthz
kill $SERVER_PID 2>/dev/null || true
```

Expected: `{"ok":true}` printed.

- [ ] **Step 4: Commit**

```bash
git add api/src/index.ts
git commit -m "feat(api): process entrypoint wiring config + tenants + square + db"
```

---

## Task 19: Deploy artifacts (systemd, Caddy, runbook)

**Files:**
- Create: `deploy/voice-api.service`
- Create: `deploy/Caddyfile`
- Create: `deploy/README-deploy.md`

- [ ] **Step 1: Create `deploy/voice-api.service`**

The systemd unit lives on the Oracle box at `/etc/systemd/system/voice-api.service`. We commit a copy in `deploy/` so it's tracked.

```ini
[Unit]
Description=Spicy Desi Voice API
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/spicydesichciago-agent/api
EnvironmentFile=/home/ubuntu/spicydesichciago-agent/api/.env
ExecStart=/usr/bin/node /home/ubuntu/spicydesichciago-agent/api/dist/index.js
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Create `deploy/Caddyfile`**

```
voice-api.spicydesi.com {
  reverse_proxy localhost:8080
  encode gzip
  log {
    output file /var/log/caddy/voice-api.log
  }
}
```

- [ ] **Step 3: Create `deploy/README-deploy.md`**

```markdown
# Deploy — Oracle Cloud ARM

One-time setup on a fresh Ubuntu 22.04 ARM Ampere A1 instance.

## 1. SSH in and install dependencies

    ssh ubuntu@<oracle-public-ip>
    sudo apt update && sudo apt -y upgrade
    sudo apt -y install curl git build-essential
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt -y install nodejs caddy

## 2. Clone and build

    cd ~
    git clone <repo-url> spicydesichciago-agent
    cd spicydesichciago-agent/api
    cp .env.example .env
    # edit .env with real keys
    npm ci
    npm run build
    mkdir -p data

## 3. Open firewall ports

    sudo ufw allow 80
    sudo ufw allow 443
    sudo ufw enable
    # Also confirm Oracle security list allows 80/443 inbound.

## 4. Install systemd unit

    sudo cp ~/spicydesichciago-agent/deploy/voice-api.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now voice-api
    sudo systemctl status voice-api

## 5. Configure Caddy

    sudo cp ~/spicydesichciago-agent/deploy/Caddyfile /etc/caddy/Caddyfile
    sudo systemctl restart caddy

Caddy auto-provisions a Let's Encrypt cert for the domain on first request.

## 6. Smoke test

    curl -fsS https://voice-api.spicydesi.com/healthz

Should print `{"ok":true}`.

## 7. Configure Square webhook

In Square Developer Dashboard → Webhooks → Subscriptions:
- URL: `https://voice-api.spicydesi.com/api/webhooks/square`
- Events: `catalog.version.updated`
- Save the signature key into `.env` as `SQUARE_WEBHOOK_SIGNATURE_KEY`.
- Set `SQUARE_WEBHOOK_URL=https://voice-api.spicydesi.com/api/webhooks/square` in `.env`.
- `sudo systemctl restart voice-api`.

## 8. Verify auth wall

    curl -i https://voice-api.spicydesi.com/api/locations?tenant=spicy-desi
    # Expected: 401
    curl -i -H "X-Tools-Auth: <secret>" \
      https://voice-api.spicydesi.com/api/locations?tenant=spicy-desi
    # Expected: 200 with locations array

## Backups

A simple cron-driven SQLite backup is added in Plan 3.
```

- [ ] **Step 4: Commit**

```bash
git add deploy/voice-api.service deploy/Caddyfile deploy/README-deploy.md
git commit -m "chore(deploy): systemd + Caddy + runbook for Oracle Cloud"
```

---

## Task 20: Final validation pass

- [ ] **Step 1: Run the full test suite**

```bash
cd api && npm test
```

Expected: all suites PASS.

- [ ] **Step 2: Typecheck**

```bash
cd api && npm run typecheck
```

Expected: no errors.

- [ ] **Step 3: Build**

```bash
cd api && npm run build
```

Expected: clean build into `api/dist`.

- [ ] **Step 4: Manual smoke (auth wall + locations 404)**

```bash
cd api
TOOLS_SHARED_SECRET=$(node -e 'console.log("x".repeat(32))') \
DB_PATH=./data/voice-agent.db \
SQUARE_ACCESS_TOKEN=fake \
SQUARE_ENVIRONMENT=sandbox \
SQUARE_WEBHOOK_SIGNATURE_KEY=fake \
CONFIGS_DIR=../configs \
SQUARE_WEBHOOK_URL=https://example.com \
PORT=18081 \
NODE_ENV=development \
LOG_LEVEL=info \
node dist/index.js &
SERVER_PID=$!
sleep 1
echo "--- healthz ---"
curl -fsS http://localhost:18081/healthz
echo
echo "--- 401 expected ---"
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:18081/api/locations?tenant=spicy-desi
echo "--- 404 unknown tenant expected ---"
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "X-Tools-Auth: $(node -e 'console.log("x".repeat(32))')" \
  http://localhost:18081/api/locations?tenant=nope
kill $SERVER_PID 2>/dev/null || true
```

Expected: `{"ok":true}`, `401`, `404`.

- [ ] **Step 5: Update README with the API surface**

Append to `/Users/milindp/Coding/Repos/spicydesichciago-agent/README.md`:

```markdown
## API endpoints (Plan 1)

All `/api/*` endpoints require `X-Tools-Auth: $TOOLS_SHARED_SECRET`. Tenant is selected via `?tenant=<slug>`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness |
| GET | `/api/locations` | List Square locations |
| GET | `/api/locations/:id/hours/today` | Today's hours + status |
| GET | `/api/locations/:id/address` | Formatted address + coords |
| GET | `/api/locations/:id/menu/search?q=` | Menu search via Square Catalog |
| GET | `/api/locations/:id/specials` | Items in the SPECIALS category |
| POST | `/api/messages` | Record a take-message (SMS hookup in Plan 2) |
| POST | `/api/transfers` | Decide transfer-vs-take-message based on owner-available hours (Twilio REST in Plan 2) |
| POST | `/api/calls/:sid/transcript` | Append transcript chunks |
| POST | `/api/webhooks/square` | Square webhook (HMAC-verified) — invalidates cache |
```

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: list Plan 1 API surface in README"
```

---

## Spec coverage check

Mapping spec sections to tasks across Parts 1–3:

| Spec section | Task(s) |
|---|---|
| Repo bootstrap | Task 1 |
| API package scaffold | Task 2 |
| Config / env validation | Task 3 |
| Tenant registry | Task 4 |
| SQLite schema (calls, transcripts, messages, transfers) | Task 5 |
| Square TTL cache | Task 6 |
| Square Locations + hours + address | Tasks 7, 11–13 |
| Square Catalog search + specials | Tasks 8, 14–15 |
| Shared-secret auth | Task 9 |
| Hono app factory + health | Task 10 |
| Skeleton message/transfer/transcript routes | Task 16 |
| Square webhook + cache invalidate | Task 17 |
| Process entrypoint | Task 18 |
| systemd + Caddy + Oracle runbook | Task 19 |
| End-to-end validation | Task 20 |
| Multi-tenant Twilio-number lookup | Task 4 (registry); used in Plan 2 |
| Twilio REST transfer (real) | **Plan 2** |
| Twilio SMS to owner / caller confirmation | **Plan 2** |
| Pipecat agent + tool client | **Plan 2** |
| Multilingual tuning + R2 backups + soft launch | **Plan 3** |

---

## Open items the user must answer (do not block Task 1; values can be filled in later)

1. Square access token (sandbox first, production later) and `square_merchant_id`.
2. Spicy Desi Twilio number (provisioned in Phase 0).
3. Owner cell number + weekly available hours (replace seed values in `configs/spicy-desi/tenant.json`).
4. Confirm "Specials" category ID in Square Catalog — replace the hardcoded `"SPECIALS"` in `api/src/index.ts` (Task 18) and `api/test/helpers/app.ts` if your category ID differs.
5. Domain for Caddy / public webhook URL — used in `deploy/Caddyfile` and `SQUARE_WEBHOOK_URL`.
