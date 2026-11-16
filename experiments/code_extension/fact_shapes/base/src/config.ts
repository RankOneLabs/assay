import { z } from "zod";
const schema = z.object({
  port: z.coerce.number().int().min(1).max(65535).default(3000),
  maxJobs: z.coerce.number().int().positive().max(10000).default(100),
  databasePath: z.string().min(1).default(":memory:"),
});
export type Config = z.infer<typeof schema>;
export function loadConfig(input: unknown): Config { return schema.parse(input); }
