import { z } from "zod";

const schema = z.object({
  port: z.coerce.number().int().min(1).max(65535).default(3000),
  maxConcurrentBuilds: z.coerce.number().int().positive().max(1000).default(10),
  maxJobs: z.coerce.number().int().positive().max(10000).default(100),
  maxEvidence: z.coerce.number().int().positive().max(1000).default(50),
  maxEvidenceBytes: z.coerce.number().int().positive().max(100000).default(50000),
  maxBulkJobs: z.coerce.number().int().positive().max(100).default(25),
  maxExportJobs: z.coerce.number().int().positive().max(1000).default(100),
  databasePath: z.string().min(1).default(":memory:"),
}).strict();

export type Config = z.infer<typeof schema>;

export function loadConfig(input: unknown): Config {
  return schema.parse(input);
}
