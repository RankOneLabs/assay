import { z } from "zod";
import { keySchema } from "./validation.ts";

export const dayMs = 86_400_000;

export interface SettingsValues {
  /** Open jobs one owner may hold before the usage report flags them. */
  wipLimit: number;
  /** Evidence content bytes the project may store before the usage report flags it. */
  evidenceQuotaBytes: number;
  defaultReviewOwner: string | null;
  /** Open jobs not updated for longer than this are reported as stale. */
  staleAfterDays: number;
}

export interface ProjectSettings extends SettingsValues {
  project: string;
  /** Zero until the project's settings are first changed. */
  revision: number;
  updatedBy: string | null;
  updatedAt: number | null;
}

export type SettingsField = keyof SettingsValues;

export interface SettingsChange {
  field: SettingsField;
  before: SettingsValues[SettingsField];
  after: SettingsValues[SettingsField];
}

export interface SettingsHistoryEntry {
  revision: number;
  actor: string;
  changes: SettingsChange[];
  reason: string | null;
  createdAt: number;
}

export const settingsDefaults: Readonly<SettingsValues> = {
  wipLimit: 5,
  evidenceQuotaBytes: 10_000_000,
  defaultReviewOwner: null,
  staleAfterDays: 14,
};

const fields = Object.keys(settingsDefaults) as SettingsField[];

export const settingsPatchSchema = z.object({
  wipLimit: z.number().int().min(1).max(1000).optional(),
  evidenceQuotaBytes: z.number().int().min(1).max(1_000_000_000_000).optional(),
  defaultReviewOwner: keySchema.nullable().optional(),
  staleAfterDays: z.number().int().min(1).max(3650).optional(),
  expectedRevision: z.number().int().min(0),
  reason: z.string().trim().min(1).max(2000).optional(),
}).strict().refine(
  value => fields.some(field => value[field] !== undefined),
  "settings change requires at least one setting",
);

/** The next values and the fields that actually differ; unchanged fields are not history. */
export function applySettings(
  current: SettingsValues,
  patch: Partial<SettingsValues>,
): { next: SettingsValues; changes: SettingsChange[] } {
  const changes = fields
    .filter(field => patch[field] !== undefined && patch[field] !== current[field])
    .map(field => ({ field, before: current[field], after: patch[field]! }));
  const next = { ...current, ...Object.fromEntries(changes.map(change => [change.field, change.after])) };
  return { next, changes };
}
