import { z } from "zod";

const envSchema = z.object({
  PORT: z.coerce.number().int().positive().default(8080),
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  LOG_LEVEL: z.enum(["trace", "debug", "info", "warn", "error", "fatal"]).default("info"),
  TOOLS_SHARED_SECRET: z.string().min(32, "TOOLS_SHARED_SECRET must be >= 32 chars"),
  DB_PATH: z.string().min(1),
  SQUARE_ACCESS_TOKEN: z.string().min(1),
  SQUARE_ENVIRONMENT: z.enum(["sandbox", "production"]),
  SQUARE_WEBHOOK_SIGNATURE_KEY: z.string().min(1),
  CONFIGS_DIR: z.string().min(1),
});

export type AppConfig = {
  port: number;
  nodeEnv: "development" | "test" | "production";
  logLevel: string;
  toolsSharedSecret: string;
  dbPath: string;
  square: {
    accessToken: string;
    environment: "sandbox" | "production";
    webhookSignatureKey: string;
  };
  configsDir: string;
};

export function loadConfig(
  env: NodeJS.ProcessEnv | Record<string, string | undefined> = process.env,
): AppConfig {
  const parsed = envSchema.parse(env);
  return {
    port: parsed.PORT,
    nodeEnv: parsed.NODE_ENV,
    logLevel: parsed.LOG_LEVEL,
    toolsSharedSecret: parsed.TOOLS_SHARED_SECRET,
    dbPath: parsed.DB_PATH,
    square: {
      accessToken: parsed.SQUARE_ACCESS_TOKEN,
      environment: parsed.SQUARE_ENVIRONMENT,
      webhookSignatureKey: parsed.SQUARE_WEBHOOK_SIGNATURE_KEY,
    },
    configsDir: parsed.CONFIGS_DIR,
  };
}
