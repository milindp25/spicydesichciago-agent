import pino from "pino";

export function makeLogger(level = "info") {
  return pino({
    level,
    transport:
      process.env.NODE_ENV === "development"
        ? { target: "pino-pretty" }
        : undefined,
  });
}

export type Logger = ReturnType<typeof makeLogger>;
