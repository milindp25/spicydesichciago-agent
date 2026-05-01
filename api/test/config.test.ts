import { describe, it, expect } from "vitest";
import { loadConfig } from "../src/config.ts";

describe("loadConfig", () => {
  it("returns a valid config when all required envs are present", () => {
    const cfg = loadConfig({
      PORT: "8080",
      NODE_ENV: "test",
      LOG_LEVEL: "info",
      TOOLS_SHARED_SECRET: "x".repeat(32),
      DB_PATH: "./data/test.db",
      SQUARE_ACCESS_TOKEN: "sandbox-token",
      SQUARE_ENVIRONMENT: "sandbox",
      SQUARE_WEBHOOK_SIGNATURE_KEY: "sig-key",
      CONFIGS_DIR: "./configs",
    });
    expect(cfg.port).toBe(8080);
    expect(cfg.toolsSharedSecret.length).toBeGreaterThanOrEqual(32);
    expect(cfg.square.environment).toBe("sandbox");
  });

  it("throws when TOOLS_SHARED_SECRET is too short", () => {
    expect(() =>
      loadConfig({
        PORT: "8080",
        NODE_ENV: "test",
        LOG_LEVEL: "info",
        TOOLS_SHARED_SECRET: "short",
        DB_PATH: "./data/test.db",
        SQUARE_ACCESS_TOKEN: "x",
        SQUARE_ENVIRONMENT: "sandbox",
        SQUARE_WEBHOOK_SIGNATURE_KEY: "x",
        CONFIGS_DIR: "./configs",
      }),
    ).toThrow();
  });

  it("rejects an invalid SQUARE_ENVIRONMENT value", () => {
    expect(() =>
      loadConfig({
        PORT: "8080",
        NODE_ENV: "test",
        LOG_LEVEL: "info",
        TOOLS_SHARED_SECRET: "x".repeat(32),
        DB_PATH: "./data/test.db",
        SQUARE_ACCESS_TOKEN: "x",
        SQUARE_ENVIRONMENT: "moon",
        SQUARE_WEBHOOK_SIGNATURE_KEY: "x",
        CONFIGS_DIR: "./configs",
      }),
    ).toThrow();
  });
});
