# Plan 1 — Part 2 (Tasks 5–12)

> Continues `2026-05-01-plan-1-foundation-and-square-api.md`. Same conventions: TDD, every step has runnable code, every task ends with a commit.

---

## Task 5: Database schema + open helper

**Files:**
- Create: `api/src/db/schema.sql`
- Create: `api/src/db/client.ts`
- Create: `api/test/db.test.ts`

- [ ] **Step 1: Write `api/src/db/schema.sql`**

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS calls (
  call_sid TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  started_at INTEGER NOT NULL,
  ended_at INTEGER,
  language TEXT,
  location_id TEXT,
  outcome TEXT
);

CREATE TABLE IF NOT EXISTS transcripts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  call_sid TEXT NOT NULL,
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  ts INTEGER NOT NULL,
  FOREIGN KEY (call_sid) REFERENCES calls(call_sid)
);

CREATE INDEX IF NOT EXISTS idx_transcripts_call_sid ON transcripts(call_sid);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  call_sid TEXT NOT NULL,
  caller_name TEXT,
  callback_number TEXT NOT NULL,
  reason TEXT NOT NULL,
  language TEXT,
  location_id TEXT,
  sent_to_owner_at INTEGER,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (call_sid) REFERENCES calls(call_sid)
);

CREATE TABLE IF NOT EXISTS transfers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  call_sid TEXT NOT NULL,
  initiated_at INTEGER NOT NULL,
  reason TEXT,
  succeeded INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (call_sid) REFERENCES calls(call_sid)
);
```

- [ ] **Step 2: Write the failing test**

Create `api/test/db.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { openDb } from "../src/db/client.ts";

describe("openDb", () => {
  it("creates schema in a fresh in-memory db", () => {
    const db = openDb(":memory:");
    const tables = db
      .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
      .all() as { name: string }[];
    const names = tables.map((t) => t.name);
    expect(names).toContain("calls");
    expect(names).toContain("transcripts");
    expect(names).toContain("messages");
    expect(names).toContain("transfers");
  });

  it("can insert and read a call row", () => {
    const db = openDb(":memory:");
    db.prepare(
      "INSERT INTO calls (call_sid, tenant_id, started_at) VALUES (?, ?, ?)"
    ).run("CA1", "spicy-desi", 1000);
    const row = db.prepare("SELECT * FROM calls WHERE call_sid = ?").get("CA1") as { tenant_id: string };
    expect(row.tenant_id).toBe("spicy-desi");
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd api && npm test -- db
```

Expected: FAIL — module not found.

- [ ] **Step 4: Implement `api/src/db/client.ts`**

We split the schema into single statements and run each via `prepare(...).run()`. This avoids loading native multi-statement helpers and keeps the surface small.

```ts
import Database, { type Database as DB } from "better-sqlite3";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));

function applySchema(db: DB, schema: string): void {
  // Split on semicolons, drop empty / comment-only fragments, run statements one at a time.
  const statements = schema
    .split(/;\s*\n/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0 && !s.startsWith("--"));
  for (const stmt of statements) {
    if (stmt.toUpperCase().startsWith("PRAGMA")) {
      db.pragma(stmt.replace(/^PRAGMA\s+/i, ""));
      continue;
    }
    db.prepare(stmt).run();
  }
}

export function openDb(path: string): DB {
  const db = new Database(path);
  db.pragma("journal_mode = WAL");
  db.pragma("foreign_keys = ON");
  const schemaPath = join(__dirname, "schema.sql");
  const schema = readFileSync(schemaPath, "utf8");
  applySchema(db, schema);
  return db;
}
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd api && npm test -- db
```

Expected: PASS — 2 passing.

- [ ] **Step 6: Commit**

```bash
git add api/src/db/schema.sql api/src/db/client.ts api/test/db.test.ts
git commit -m "feat(api): SQLite schema + openDb helper"
```

---

## Task 6: Square TTL cache

**Files:**
- Create: `api/src/square/cache.ts`
- Create: `api/test/cache.test.ts`

- [ ] **Step 1: Write the failing test**

Create `api/test/cache.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { TtlCache } from "../src/square/cache.ts";

describe("TtlCache", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("returns cached value within ttl", async () => {
    const cache = new TtlCache<string>(1000);
    let calls = 0;
    const loader = async () => { calls++; return "v1"; };
    expect(await cache.getOrLoad("k", loader)).toBe("v1");
    expect(await cache.getOrLoad("k", loader)).toBe("v1");
    expect(calls).toBe(1);
  });

  it("reloads after ttl expires", async () => {
    const cache = new TtlCache<string>(1000);
    let calls = 0;
    const loader = async () => { calls++; return `v${calls}`; };
    expect(await cache.getOrLoad("k", loader)).toBe("v1");
    vi.advanceTimersByTime(1500);
    expect(await cache.getOrLoad("k", loader)).toBe("v2");
    expect(calls).toBe(2);
  });

  it("invalidate removes a single key", async () => {
    const cache = new TtlCache<string>(60_000);
    let calls = 0;
    const loader = async () => { calls++; return `v${calls}`; };
    await cache.getOrLoad("k1", loader);
    cache.invalidate("k1");
    await cache.getOrLoad("k1", loader);
    expect(calls).toBe(2);
  });

  it("clear removes all keys", async () => {
    const cache = new TtlCache<string>(60_000);
    let calls = 0;
    await cache.getOrLoad("k1", async () => { calls++; return "a"; });
    await cache.getOrLoad("k2", async () => { calls++; return "b"; });
    cache.clear();
    await cache.getOrLoad("k1", async () => { calls++; return "a"; });
    expect(calls).toBe(3);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd api && npm test -- cache
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `api/src/square/cache.ts`**

```ts
type Entry<T> = { value: T; expiresAt: number };

export class TtlCache<T> {
  private store = new Map<string, Entry<T>>();
  constructor(private ttlMs: number) {}

  async getOrLoad(key: string, loader: () => Promise<T>): Promise<T> {
    const now = Date.now();
    const hit = this.store.get(key);
    if (hit && hit.expiresAt > now) return hit.value;
    const value = await loader();
    this.store.set(key, { value, expiresAt: now + this.ttlMs });
    return value;
  }

  invalidate(key: string): void {
    this.store.delete(key);
  }

  clear(): void {
    this.store.clear();
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd api && npm test -- cache
```

Expected: PASS — 4 passing.

- [ ] **Step 5: Commit**

```bash
git add api/src/square/cache.ts api/test/cache.test.ts
git commit -m "feat(api): TTL cache for Square responses"
```

---

## Task 7: Square LocationsService — list + hours + address

**Files:**
- Create: `api/src/square/client.ts`
- Create: `api/src/square/locations.ts`
- Create: `api/test/helpers/square_mock.ts`
- Create: `api/test/locations.unit.test.ts`

- [ ] **Step 1: Create `api/test/helpers/square_mock.ts`**

```ts
import type { LocationsApi, CatalogApi } from "../../src/square/client.ts";

export function makeMockLocationsApi(locations: any[]): LocationsApi {
  return {
    listLocations: async () => ({ result: { locations } }),
    retrieveLocation: async (id: string) => ({
      result: { location: locations.find((l) => l.id === id) },
    }),
  };
}

export function makeMockCatalogApi(items: any[]): CatalogApi {
  return {
    searchCatalogItems: async (req: { textFilter?: string; categoryIds?: string[] }) => {
      let result = items;
      if (req.textFilter) {
        const q = req.textFilter.toLowerCase();
        result = result.filter((i) => i.itemData.name.toLowerCase().includes(q));
      }
      if (req.categoryIds && req.categoryIds.length > 0) {
        result = result.filter((i) =>
          (i.itemData.categories ?? []).some((c: any) => req.categoryIds!.includes(c.id))
        );
      }
      return { result: { items: result } };
    },
    listCatalog: async () => ({ result: { objects: items } }),
  };
}
```

- [ ] **Step 2: Write the failing test**

Create `api/test/locations.unit.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { TtlCache } from "../src/square/cache.ts";
import { LocationsService } from "../src/square/locations.ts";
import { makeMockLocationsApi } from "./helpers/square_mock.ts";

const SAMPLE = [
  {
    id: "L1",
    name: "Spicy Desi Loop",
    address: { addressLine1: "111 W Madison", locality: "Chicago", administrativeDistrictLevel1: "IL", postalCode: "60602" },
    coordinates: { latitude: 41.881, longitude: -87.631 },
    businessHours: {
      periods: [
        { dayOfWeek: "MON", startLocalTime: "11:00:00", endLocalTime: "21:30:00" },
        { dayOfWeek: "TUE", startLocalTime: "11:00:00", endLocalTime: "21:30:00" },
      ],
    },
    timezone: "America/Chicago",
  },
];

describe("LocationsService", () => {
  it("listLocations returns id, name, formatted address", async () => {
    const svc = new LocationsService(makeMockLocationsApi(SAMPLE), new TtlCache(60_000));
    const list = await svc.listLocations();
    expect(list).toHaveLength(1);
    expect(list[0]).toMatchObject({ location_id: "L1", name: "Spicy Desi Loop" });
    expect(list[0].address).toContain("111 W Madison");
  });

  it("getHoursToday returns open status on a Monday at 2pm Chicago", async () => {
    const svc = new LocationsService(makeMockLocationsApi(SAMPLE), new TtlCache(60_000));
    const monday2pm = new Date("2026-01-05T20:00:00Z");
    const r = await svc.getHoursToday("L1", monday2pm);
    expect(r.open).toBe("11:00");
    expect(r.close).toBe("21:30");
    expect(r.status).toBe("open");
  });

  it("getHoursToday returns closed status outside hours", async () => {
    const svc = new LocationsService(makeMockLocationsApi(SAMPLE), new TtlCache(60_000));
    const earlyMonday = new Date("2026-01-05T12:00:00Z");
    const r = await svc.getHoursToday("L1", earlyMonday);
    expect(r.status).toBe("closed");
  });

  it("getAddress returns formatted address with coords", async () => {
    const svc = new LocationsService(makeMockLocationsApi(SAMPLE), new TtlCache(60_000));
    const a = await svc.getAddress("L1");
    expect(a.formatted).toContain("111 W Madison");
    expect(a.lat).toBeCloseTo(41.881);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd api && npm test -- locations.unit
```

Expected: FAIL — module not found.

- [ ] **Step 4: Implement `api/src/square/client.ts`**

```ts
import { Client, Environment } from "square";

export type LocationsApi = {
  listLocations: () => Promise<{ result: { locations?: any[] } }>;
  retrieveLocation: (id: string) => Promise<{ result: { location?: any } }>;
};

export type CatalogApi = {
  searchCatalogItems: (req: {
    textFilter?: string;
    categoryIds?: string[];
  }) => Promise<{ result: { items?: any[] } }>;
  listCatalog: (opts?: { types?: string }) => Promise<{ result: { objects?: any[] } }>;
};

export function makeSquareClient(opts: { accessToken: string; environment: "sandbox" | "production" }) {
  return new Client({
    accessToken: opts.accessToken,
    environment: opts.environment === "production" ? Environment.Production : Environment.Sandbox,
  });
}

export function locationsApiFromClient(c: Client): LocationsApi {
  return {
    listLocations: () => c.locationsApi.listLocations() as any,
    retrieveLocation: (id) => c.locationsApi.retrieveLocation(id) as any,
  };
}

export function catalogApiFromClient(c: Client): CatalogApi {
  return {
    searchCatalogItems: (req) =>
      c.catalogApi.searchCatalogItems({
        textFilter: req.textFilter,
        categoryIds: req.categoryIds,
      }) as any,
    listCatalog: (opts) => c.catalogApi.listCatalog(undefined, opts?.types) as any,
  };
}
```

- [ ] **Step 5: Implement `api/src/square/locations.ts`**

```ts
import { TtlCache } from "./cache.ts";
import type { LocationsApi } from "./client.ts";

export type LocationListItem = {
  location_id: string;
  name: string;
  address: string;
};

export type HoursToday = {
  open: string | null;
  close: string | null;
  status: "open" | "closed" | "closing_soon";
  next_open?: string;
};

export type AddressInfo = {
  formatted: string;
  lat: number | null;
  lng: number | null;
};

const DOW_KEYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"] as const;

function formatAddr(addr: any): string {
  if (!addr) return "";
  const parts = [
    addr.addressLine1,
    addr.locality,
    addr.administrativeDistrictLevel1,
    addr.postalCode,
  ].filter(Boolean);
  return parts.join(", ");
}

function hhmm(t: string | undefined): string | null {
  if (!t) return null;
  return t.slice(0, 5);
}

function dayOfWeekInTz(date: Date, tz: string): typeof DOW_KEYS[number] {
  const formatter = new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short" });
  const short = formatter.format(date).toUpperCase().slice(0, 3);
  return short as typeof DOW_KEYS[number];
}

function timeInTz(date: Date, tz: string): string {
  const f = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return f.format(date).replace(/^24:/, "00:");
}

function toMinutes(hhmmStr: string): number {
  const [h, m] = hhmmStr.split(":").map((n) => parseInt(n, 10));
  return (h ?? 0) * 60 + (m ?? 0);
}

export class LocationsService {
  constructor(private api: LocationsApi, private cache: TtlCache<any[]>) {}

  private async loadLocations(): Promise<any[]> {
    return this.cache.getOrLoad("all", async () => {
      const r = await this.api.listLocations();
      return r.result.locations ?? [];
    });
  }

  async listLocations(): Promise<LocationListItem[]> {
    const locs = await this.loadLocations();
    return locs.map((l) => ({
      location_id: l.id,
      name: l.name,
      address: formatAddr(l.address),
    }));
  }

  async getHoursToday(locationId: string, now = new Date()): Promise<HoursToday> {
    const locs = await this.loadLocations();
    const loc = locs.find((l) => l.id === locationId);
    if (!loc) throw new Error(`location not found: ${locationId}`);
    const tz: string = loc.timezone ?? "America/Chicago";
    const dow = dayOfWeekInTz(now, tz);
    const period = (loc.businessHours?.periods ?? []).find((p: any) => p.dayOfWeek === dow);
    if (!period) return { open: null, close: null, status: "closed" };
    const open = hhmm(period.startLocalTime);
    const close = hhmm(period.endLocalTime);
    const cur = timeInTz(now, tz);
    let status: HoursToday["status"] = "closed";
    if (open && close && cur >= open && cur < close) {
      const closeMinutes = toMinutes(close);
      const curMinutes = toMinutes(cur);
      status = closeMinutes - curMinutes <= 30 ? "closing_soon" : "open";
    }
    return { open, close, status };
  }

  async getAddress(locationId: string): Promise<AddressInfo> {
    const locs = await this.loadLocations();
    const loc = locs.find((l) => l.id === locationId);
    if (!loc) throw new Error(`location not found: ${locationId}`);
    return {
      formatted: formatAddr(loc.address),
      lat: loc.coordinates?.latitude ?? null,
      lng: loc.coordinates?.longitude ?? null,
    };
  }
}
```

- [ ] **Step 6: Run test to verify it passes**

```bash
cd api && npm test -- locations.unit
```

Expected: PASS — 4 passing.

- [ ] **Step 7: Commit**

```bash
git add api/src/square/client.ts api/src/square/locations.ts \
        api/test/helpers/square_mock.ts api/test/locations.unit.test.ts
git commit -m "feat(api): square LocationsService — list, hours-today, address"
```

---

## Task 8: Square CatalogService — menu search + specials

**Files:**
- Create: `api/src/square/catalog.ts`
- Create: `api/test/catalog.unit.test.ts`

- [ ] **Step 1: Write the failing test**

Create `api/test/catalog.unit.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { TtlCache } from "../src/square/cache.ts";
import { CatalogService } from "../src/square/catalog.ts";
import { makeMockCatalogApi } from "./helpers/square_mock.ts";

const ITEMS = [
  {
    id: "I1",
    type: "ITEM",
    itemData: {
      name: "Chicken Tikka Masala",
      description: "Boneless chicken in creamy tomato sauce",
      categories: [{ id: "MAINS" }],
      variations: [
        { id: "V1", itemVariationData: { priceMoney: { amount: 1899, currency: "USD" } } },
      ],
    },
  },
  {
    id: "I2",
    type: "ITEM",
    itemData: {
      name: "Paneer Tikka",
      description: "Grilled paneer cubes",
      categories: [{ id: "STARTERS" }, { id: "SPECIALS" }],
      variations: [
        { id: "V2", itemVariationData: { priceMoney: { amount: 1599, currency: "USD" } } },
      ],
    },
  },
];

describe("CatalogService", () => {
  it("searchMenu finds matching items by name", async () => {
    const svc = new CatalogService(makeMockCatalogApi(ITEMS), new TtlCache(60_000), "SPECIALS");
    const r = await svc.searchMenu("paneer");
    expect(r).toHaveLength(1);
    expect(r[0]?.name).toBe("Paneer Tikka");
    expect(r[0]?.price).toBe("$15.99");
  });

  it("searchMenu returns empty array when nothing matches", async () => {
    const svc = new CatalogService(makeMockCatalogApi(ITEMS), new TtlCache(60_000), "SPECIALS");
    const r = await svc.searchMenu("sushi");
    expect(r).toEqual([]);
  });

  it("getSpecials returns only items in the specials category", async () => {
    const svc = new CatalogService(makeMockCatalogApi(ITEMS), new TtlCache(60_000), "SPECIALS");
    const r = await svc.getSpecials();
    expect(r).toHaveLength(1);
    expect(r[0]?.name).toBe("Paneer Tikka");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd api && npm test -- catalog.unit
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `api/src/square/catalog.ts`**

```ts
import { TtlCache } from "./cache.ts";
import type { CatalogApi } from "./client.ts";

export type MenuItem = {
  name: string;
  description: string;
  price: string;
  category: string | null;
  dietary_tags: string[];
};

function formatMoney(amount: number | undefined, currency: string | undefined): string {
  if (amount == null) return "";
  const value = amount / 100;
  if (currency === "USD") return `$${value.toFixed(2)}`;
  return `${value.toFixed(2)} ${currency ?? ""}`.trim();
}

function toMenuItem(item: any): MenuItem {
  const variation = item.itemData.variations?.[0]?.itemVariationData?.priceMoney;
  return {
    name: item.itemData.name ?? "",
    description: item.itemData.description ?? "",
    price: formatMoney(variation?.amount, variation?.currency),
    category: item.itemData.categories?.[0]?.id ?? null,
    dietary_tags: [],
  };
}

export class CatalogService {
  constructor(
    private api: CatalogApi,
    private cache: TtlCache<any[]>,
    private specialsCategoryId: string
  ) {}

  async searchMenu(query: string): Promise<MenuItem[]> {
    const r = await this.api.searchCatalogItems({ textFilter: query });
    return (r.result.items ?? []).map(toMenuItem);
  }

  async getSpecials(): Promise<MenuItem[]> {
    const items = await this.cache.getOrLoad("specials", async () => {
      const r = await this.api.searchCatalogItems({ categoryIds: [this.specialsCategoryId] });
      return r.result.items ?? [];
    });
    return items.map(toMenuItem);
  }

  invalidate(): void {
    this.cache.clear();
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd api && npm test -- catalog.unit
```

Expected: PASS — 3 passing.

- [ ] **Step 5: Commit**

```bash
git add api/src/square/catalog.ts api/test/catalog.unit.test.ts
git commit -m "feat(api): square CatalogService — menu search + specials"
```

---

## Task 9: Auth middleware

**Files:**
- Create: `api/src/auth.ts`
- Create: `api/test/auth.test.ts`

- [ ] **Step 1: Write the failing test**

Create `api/test/auth.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { Hono } from "hono";
import { sharedSecretAuth } from "../src/auth.ts";

function buildApp(secret: string) {
  const app = new Hono();
  app.use("/api/*", sharedSecretAuth(secret));
  app.get("/api/ping", (c) => c.json({ ok: true }));
  app.get("/healthz", (c) => c.json({ ok: true }));
  return app;
}

describe("sharedSecretAuth", () => {
  it("rejects missing header with 401", async () => {
    const app = buildApp("s".repeat(32));
    const r = await app.request("/api/ping");
    expect(r.status).toBe(401);
  });

  it("rejects wrong secret with 401", async () => {
    const app = buildApp("s".repeat(32));
    const r = await app.request("/api/ping", { headers: { "X-Tools-Auth": "wrong" } });
    expect(r.status).toBe(401);
  });

  it("accepts correct secret", async () => {
    const app = buildApp("s".repeat(32));
    const r = await app.request("/api/ping", { headers: { "X-Tools-Auth": "s".repeat(32) } });
    expect(r.status).toBe(200);
  });

  it("does not gate non-/api paths", async () => {
    const app = buildApp("s".repeat(32));
    const r = await app.request("/healthz");
    expect(r.status).toBe(200);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd api && npm test -- auth
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `api/src/auth.ts`**

```ts
import type { MiddlewareHandler } from "hono";
import { timingSafeEqual } from "node:crypto";

export function sharedSecretAuth(expected: string): MiddlewareHandler {
  const expectedBuf = Buffer.from(expected);
  return async (c, next) => {
    const provided = c.req.header("X-Tools-Auth") ?? "";
    const providedBuf = Buffer.from(provided);
    if (
      providedBuf.length !== expectedBuf.length ||
      !timingSafeEqual(providedBuf, expectedBuf)
    ) {
      return c.json({ error: "unauthorized" }, 401);
    }
    await next();
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd api && npm test -- auth
```

Expected: PASS — 4 passing.

- [ ] **Step 5: Commit**

```bash
git add api/src/auth.ts api/test/auth.test.ts
git commit -m "feat(api): shared-secret auth middleware with timing-safe compare"
```

---

## Task 10: Hono app factory + health route + test harness

**Files:**
- Create: `api/src/server.ts`
- Create: `api/src/routes/health.ts`
- Create: `api/test/helpers/app.ts`
- Create: `api/test/health.test.ts`

- [ ] **Step 1: Write the failing test**

Create `api/test/health.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { buildTestApp } from "./helpers/app.ts";

describe("GET /healthz", () => {
  it("returns 200 with ok body", async () => {
    const { app } = buildTestApp();
    const r = await app.request("/healthz");
    expect(r.status).toBe(200);
    expect(await r.json()).toEqual({ ok: true });
  });
});
```

- [ ] **Step 2: Implement `api/src/routes/health.ts`**

```ts
import { Hono } from "hono";

export const healthRouter = new Hono();
healthRouter.get("/healthz", (c) => c.json({ ok: true }));
```

- [ ] **Step 3: Implement `api/src/server.ts`**

```ts
import { Hono } from "hono";
import { healthRouter } from "./routes/health.ts";
import { sharedSecretAuth } from "./auth.ts";
import type { LocationsService } from "./square/locations.ts";
import type { CatalogService } from "./square/catalog.ts";
import type { TenantRegistry } from "./types.ts";
import type { Database as DB } from "better-sqlite3";

export type SquareWebhookHookDeps = {
  signatureKey: string;
  notifyUrl: string;
  onInvalidate: () => void;
};

export type AppDeps = {
  toolsSharedSecret: string;
  tenants: TenantRegistry;
  db: DB;
  locationsByTenant: (tenantSlug: string) => LocationsService;
  catalogByTenant: (tenantSlug: string) => CatalogService;
  squareWebhook: SquareWebhookHookDeps;
};

export function buildApp(deps: AppDeps) {
  const app = new Hono<{ Variables: { deps: AppDeps } }>();

  app.use("*", async (c, next) => {
    c.set("deps", deps);
    await next();
  });

  app.route("/", healthRouter);
  app.use("/api/*", sharedSecretAuth(deps.toolsSharedSecret));

  return app;
}
```

- [ ] **Step 4: Implement `api/test/helpers/app.ts`**

```ts
import { buildApp, type AppDeps } from "../../src/server.ts";
import { openDb } from "../../src/db/client.ts";
import { TtlCache } from "../../src/square/cache.ts";
import { LocationsService } from "../../src/square/locations.ts";
import { CatalogService } from "../../src/square/catalog.ts";
import { makeMockLocationsApi, makeMockCatalogApi } from "./square_mock.ts";

export function buildTestApp(opts: {
  locations?: any[];
  catalogItems?: any[];
  secret?: string;
} = {}) {
  const secret = opts.secret ?? "s".repeat(32);
  const db = openDb(":memory:");
  const locationsService = new LocationsService(
    makeMockLocationsApi(opts.locations ?? []),
    new TtlCache(60_000)
  );
  const catalogService = new CatalogService(
    makeMockCatalogApi(opts.catalogItems ?? []),
    new TtlCache(60_000),
    "SPECIALS"
  );
  const deps: AppDeps = {
    toolsSharedSecret: secret,
    tenants: {
      tenants: {
        "spicy-desi": {
          slug: "spicy-desi",
          name: "Spicy Desi",
          twilioNumber: "+15555550100",
          ownerPhone: "+15555550199",
          ownerAvailable: { tz: "America/Chicago", weekly: { mon: ["11:00", "21:30"] } },
          squareMerchantId: "M1",
          languages: ["en"],
          smsConfirmationToCaller: true,
          locationOverrides: {},
          faq: "",
          locationNotes: "",
        },
      },
      byTwilioNumber: { "+15555550100": "spicy-desi" },
    },
    db,
    locationsByTenant: () => locationsService,
    catalogByTenant: () => catalogService,
    squareWebhook: {
      signatureKey: "key",
      notifyUrl: "https://x.example.com/api/webhooks/square",
      onInvalidate: () => {},
    },
  };
  const app = buildApp(deps);
  return { app, deps, secret };
}
```

- [ ] **Step 5: Run tests**

```bash
cd api && npm test -- health
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/src/server.ts api/src/routes/health.ts \
        api/test/helpers/app.ts api/test/health.test.ts
git commit -m "feat(api): Hono app factory + health route + test harness"
```

---

## Task 11: GET /api/locations route

**Files:**
- Create: `api/src/routes/locations.ts`
- Create: `api/test/locations.test.ts`
- Modify: `api/src/server.ts`

- [ ] **Step 1: Write the failing test**

Create `api/test/locations.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { buildTestApp } from "./helpers/app.ts";

const SAMPLE = [
  { id: "L1", name: "Loop", address: { addressLine1: "111 W Madison" }, businessHours: { periods: [] } },
];

describe("GET /api/locations", () => {
  it("requires auth", async () => {
    const { app } = buildTestApp({ locations: SAMPLE });
    const r = await app.request("/api/locations?tenant=spicy-desi");
    expect(r.status).toBe(401);
  });

  it("returns 400 when tenant missing", async () => {
    const { app, secret } = buildTestApp({ locations: SAMPLE });
    const r = await app.request("/api/locations", {
      headers: { "X-Tools-Auth": secret },
    });
    expect(r.status).toBe(400);
  });

  it("returns 404 for unknown tenant", async () => {
    const { app, secret } = buildTestApp({ locations: SAMPLE });
    const r = await app.request("/api/locations?tenant=nope", {
      headers: { "X-Tools-Auth": secret },
    });
    expect(r.status).toBe(404);
  });

  it("returns location list", async () => {
    const { app, secret } = buildTestApp({ locations: SAMPLE });
    const r = await app.request("/api/locations?tenant=spicy-desi", {
      headers: { "X-Tools-Auth": secret },
    });
    expect(r.status).toBe(200);
    const body = (await r.json()) as { locations: any[] };
    expect(body.locations).toHaveLength(1);
    expect(body.locations[0].location_id).toBe("L1");
  });
});
```

- [ ] **Step 2: Implement `api/src/routes/locations.ts`**

```ts
import { Hono } from "hono";
import { z } from "zod";
import type { AppDeps } from "../server.ts";

const querySchema = z.object({ tenant: z.string().min(1) });

export const locationsRouter = new Hono<{ Variables: { deps: AppDeps } }>();

locationsRouter.get("/api/locations", async (c) => {
  const parsed = querySchema.safeParse({ tenant: c.req.query("tenant") });
  if (!parsed.success) return c.json({ error: "tenant query param required" }, 400);
  const deps = c.get("deps");
  if (!deps.tenants.tenants[parsed.data.tenant]) {
    return c.json({ error: "tenant not found" }, 404);
  }
  const svc = deps.locationsByTenant(parsed.data.tenant);
  const locations = await svc.listLocations();
  return c.json({ locations });
});
```

- [ ] **Step 3: Wire the router in `api/src/server.ts`**

Add import alongside `healthRouter`:

```ts
import { locationsRouter } from "./routes/locations.ts";
```

Mount it after the auth middleware line, before `return app`:

```ts
  app.route("/", locationsRouter);

  return app;
```

- [ ] **Step 4: Run tests**

```bash
cd api && npm test -- locations.test
```

Expected: PASS — 4 passing.

- [ ] **Step 5: Commit**

```bash
git add api/src/routes/locations.ts api/src/server.ts api/test/locations.test.ts
git commit -m "feat(api): GET /api/locations route"
```

---

## Task 12: GET /api/locations/:id/hours/today route

**Files:**
- Create: `api/src/routes/hours.ts`
- Create: `api/test/hours.test.ts`
- Modify: `api/src/server.ts`

- [ ] **Step 1: Write the failing test**

Create `api/test/hours.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { buildTestApp } from "./helpers/app.ts";

const SAMPLE = [
  {
    id: "L1",
    name: "Loop",
    address: { addressLine1: "111 W Madison" },
    businessHours: {
      periods: [
        { dayOfWeek: "MON", startLocalTime: "11:00:00", endLocalTime: "21:30:00" },
      ],
    },
    timezone: "America/Chicago",
  },
];

describe("GET /api/locations/:id/hours/today", () => {
  it("returns 200 with hours payload", async () => {
    const { app, secret } = buildTestApp({ locations: SAMPLE });
    const r = await app.request("/api/locations/L1/hours/today?tenant=spicy-desi", {
      headers: { "X-Tools-Auth": secret },
    });
    expect(r.status).toBe(200);
    const body = (await r.json()) as { open: string | null; close: string | null; status: string };
    expect(body.open).toBe("11:00");
    expect(body.close).toBe("21:30");
    expect(["open", "closed", "closing_soon"]).toContain(body.status);
  });

  it("returns 404 for unknown location", async () => {
    const { app, secret } = buildTestApp({ locations: SAMPLE });
    const r = await app.request("/api/locations/Lnope/hours/today?tenant=spicy-desi", {
      headers: { "X-Tools-Auth": secret },
    });
    expect(r.status).toBe(404);
  });
});
```

- [ ] **Step 2: Implement `api/src/routes/hours.ts`**

```ts
import { Hono } from "hono";
import type { AppDeps } from "../server.ts";

export const hoursRouter = new Hono<{ Variables: { deps: AppDeps } }>();

hoursRouter.get("/api/locations/:id/hours/today", async (c) => {
  const tenant = c.req.query("tenant");
  if (!tenant) return c.json({ error: "tenant query param required" }, 400);
  const deps = c.get("deps");
  if (!deps.tenants.tenants[tenant]) return c.json({ error: "tenant not found" }, 404);
  const svc = deps.locationsByTenant(tenant);
  try {
    const hours = await svc.getHoursToday(c.req.param("id"));
    return c.json(hours);
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
import { hoursRouter } from "./routes/hours.ts";
// ...
  app.route("/", hoursRouter);
```

- [ ] **Step 4: Run tests**

```bash
cd api && npm test -- hours.test
```

Expected: PASS — 2 passing.

- [ ] **Step 5: Commit**

```bash
git add api/src/routes/hours.ts api/src/server.ts api/test/hours.test.ts
git commit -m "feat(api): GET /api/locations/:id/hours/today route"
```

---

End of Part 2. Continue in `2026-05-01-plan-1-foundation-and-square-api-part-3.md`.
