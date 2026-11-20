import { z } from "zod";
import { keySchema } from "./validation.ts";

export type DeliveryStatus = "pending" | "delivered" | "dead";

export interface WebhookEndpoint {
  id: string;
  project: string;
  url: string;
  active: boolean;
  revision: number;
  secretHint: string;
  createdAt: number;
  updatedAt: number;
}

export interface WebhookDelivery {
  id: number;
  webhookId: string;
  eventSequence: number;
  action: string;
  payload: string;
  status: DeliveryStatus;
  attempts: number;
  nextAttemptAt: number;
  leaseOwner: string | null;
  leaseExpiresAt: number | null;
  lastStatus: number | null;
  updatedAt: number;
}

export type AttemptOutcome = Pick<WebhookDelivery, "status" | "attempts" | "nextAttemptAt">;

/** Retries double from one minute, are capped at six hours, and stop after six attempts. */
export const deliveryPolicy = { maxAttempts: 6, baseDelayMs: 60_000, maxDelayMs: 6 * 60 * 60_000 };

const privateSuffixes = [".localhost", ".local", ".internal", ".lan", ".home.arpa"];

/** The reason a URL may not receive webhooks, or null when it may. */
function urlProblem(value: string): string | null {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return "webhook url must be an absolute url";
  }
  if (url.protocol !== "https:") return "webhook url must use https";
  if (url.username !== "" || url.password !== "") return "webhook url must not carry credentials";
  if (privateHost(url.hostname)) return "webhook url must name a public host";
  return null;
}

function privateHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/\.$/, "");
  const ipv4 = /^(\d+)\.(\d+)\.(\d+)\.(\d+)$/.exec(host);
  if (ipv4) {
    const [first, second] = [Number(ipv4[1]), Number(ipv4[2])];
    return first === 0 || first === 10 || first === 127 || first >= 224
      || (first === 100 && second >= 64 && second <= 127)
      || (first === 169 && second === 254)
      || (first === 172 && second >= 16 && second <= 31)
      || (first === 192 && second === 168);
  }
  // Single-label names, IPv6 literals among them, are refused as local-network addresses.
  return !host.includes(".") || privateSuffixes.some(suffix => host.endsWith(suffix));
}

/** URLs are stored normalized so one endpoint cannot be registered twice under two spellings. */
const webhookUrlSchema = z.string().trim().min(1).max(2000).superRefine((value, context) => {
  const problem = urlProblem(value);
  if (problem !== null) context.addIssue({ code: "custom", message: problem });
}).transform(value => new URL(value).href);

export const createWebhookSchema = z.object({
  id: keySchema,
  url: webhookUrlSchema,
  active: z.boolean().default(true),
}).strict();

export const patchWebhookSchema = z.object({
  url: webhookUrlSchema.optional(),
  active: z.boolean().optional(),
  expectedRevision: z.number().int().positive(),
}).strict().refine(
  value => value.url !== undefined || value.active !== undefined,
  "patch requires a changed field",
);

export const claimSchema = z.object({
  worker: keySchema,
  limit: z.number().int().min(1).max(50).default(10),
  leaseMs: z.number().int().min(1000).max(300_000).default(30_000),
}).strict();

/** Status 0 records an attempt that got no response at all, such as a timeout. */
export const reportSchema = z.object({
  leaseToken: z.uuid(),
  status: z.number().int().min(0).max(599),
}).strict();

/** Where a delivery goes once an attempt that got the given response status is recorded. */
export function attemptOutcome(previousAttempts: number, status: number, now: number): AttemptOutcome {
  const attempts = previousAttempts + 1;
  if (status >= 200 && status < 300) return { status: "delivered", attempts, nextAttemptAt: now };
  // 410 Gone is the receiver saying it will never accept this delivery.
  if (status === 410 || attempts >= deliveryPolicy.maxAttempts) return { status: "dead", attempts, nextAttemptAt: now };
  const delay = Math.min(deliveryPolicy.baseDelayMs * 2 ** (attempts - 1), deliveryPolicy.maxDelayMs);
  return { status: "pending", attempts, nextAttemptAt: now + delay };
}

export function secretHint(secret: string): string {
  return `...${secret.slice(-4)}`;
}

/** The exact request a delivery worker sends; the signature is an HMAC of the body. */
export function signedRequest(url: string, secret: string, delivery: WebhookDelivery, timestamp: number) {
  return {
    method: "POST" as const,
    url,
    headers: {
      "content-type": "application/json",
      "webhook-id": String(delivery.id),
      "webhook-event": delivery.action,
      "webhook-timestamp": String(timestamp),
      "webhook-signature": `sha256=${new Bun.CryptoHasher("sha256", secret).update(delivery.payload).digest("hex")}`,
    },
    body: delivery.payload,
  };
}
