import type { Context } from "hono";
import { z } from "zod";
import { ServiceError } from "../domain/errors.ts";
import type { Principal } from "../domain/models.ts";
import { keySchema } from "../domain/validation.ts";

export function principal(c: Context): Principal {
  return {
    id: keySchema.parse(c.req.header("x-principal") ?? ""),
    project: keySchema.parse(c.req.header("x-project") ?? ""),
  };
}

export function identifier(c: Context, name = "id"): string {
  return keySchema.parse(c.req.param(name));
}

export async function json(c: Context): Promise<unknown> {
  const type = c.req.header("content-type") ?? "";
  if (!/^application\/json(?:\s*;|$)/i.test(type)) {
    throw new ServiceError(400, "invalid_content_type", "application/json required");
  }
  try {
    return await c.req.json<unknown>();
  } catch {
    throw new ServiceError(400, "invalid_json", "request body is not valid JSON");
  }
}

export function integerQuery(c: Context, key: string, fallback: number, max: number): number {
  const value = c.req.query(key);
  if (value === undefined) return fallback;
  return z.coerce.number().int().min(0).max(max).parse(value);
}

export function handleError(error: Error, c: Context): Response {
  if (error instanceof ServiceError) {
    return c.json({ error: error.code, message: error.message, detail: error.detail }, error.status);
  }
  if (error instanceof z.ZodError) {
    return c.json({ error: "validation_failed", issues: error.issues }, 400);
  }
  // Database and programming errors remain opaque to clients.
  return c.json({ error: "internal_error" }, 500);
}
