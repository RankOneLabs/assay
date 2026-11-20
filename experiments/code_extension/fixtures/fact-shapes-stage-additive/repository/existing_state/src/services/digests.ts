import type { Database } from "bun:sqlite";
import { values as stages, type Stage } from "../../stage/types.ts";
import { values as kinds, type EvidenceKind } from "../../evidence_kind/types.ts";
import type { Page, Principal } from "../domain/models.ts";
import { readAccess } from "../domain/access_levels.ts";
import { checksum, matchesChecksum } from "../domain/checksum.ts";
import { conflict, limitExceeded, missing } from "../domain/errors.ts";
import { nextRun } from "../domain/schedules.ts";
import {
  digestIdSchema, digestPageSchema, dueSchema, generateSchema,
  recurrenceSchema, schedulePatchSchema, scheduleSchema,
} from "../domain/digest_validation.ts";
import { evidenceKindLabel, stageLabel } from "../presentation/labels.ts";
import { DigestScheduleRepository, type DigestSchedule } from "../repositories/digest_schedules.ts";
import { DigestRepository, type StoredDigest } from "../repositories/digests.ts";
import { GrantRepository } from "../repositories/grants.ts";
import { AccessService } from "./access.ts";

const MAX_SCHEDULES_PER_PRINCIPAL = 10;

export interface DigestContent {
  jobs: { created: number; changed: number };
  transitions: { stage: Stage; label: string; count: number }[];
  evidence: { kind: EvidenceKind; label: string; count: number }[];
}

export interface Digest extends Omit<StoredDigest, "content"> {
  content: DigestContent;
}

function view(stored: StoredDigest): Digest {
  return { ...stored, content: JSON.parse(stored.content) as DigestContent };
}

export class DigestService {
  constructor(
    private readonly db: Database,
    private readonly schedules: DigestScheduleRepository,
    private readonly digests: DigestRepository,
    private readonly grants: GrantRepository,
    private readonly access: AccessService,
    private readonly now: () => number,
  ) {}

  createSchedule(actor: Principal, input: unknown): DigestSchedule {
    this.access.require(actor, readAccess);
    const { id, ...values } = scheduleSchema.parse(input);
    return this.db.transaction(() => {
      if (this.schedules.owned(actor).length >= MAX_SCHEDULES_PER_PRINCIPAL) {
        limitExceeded("digest schedule limit reached");
      }
      const now = this.now();
      return this.schedules.create(id, actor, values, nextRun(values, now), now);
    })();
  }

  listSchedules(actor: Principal): DigestSchedule[] {
    this.access.require(actor, readAccess);
    return this.schedules.owned(actor);
  }

  updateSchedule(actor: Principal, id: string, input: unknown): DigestSchedule {
    this.access.require(actor, readAccess);
    const { expectedRevision, ...changes } = schedulePatchSchema.parse(input);
    return this.db.transaction(() => {
      const current = this.ownSchedule(actor, id);
      const cadence = changes.cadence ?? current.cadence;
      const values = recurrenceSchema.parse({
        cadence,
        // Moving to a daily cadence drops the weekday unless one was sent.
        weekday: changes.weekday !== undefined ? changes.weekday : cadence === "daily" ? null : current.weekday,
        hour: changes.hour ?? current.hour,
        utcOffsetMinutes: changes.utcOffsetMinutes ?? current.utcOffsetMinutes,
        enabled: changes.enabled ?? current.enabled,
      });
      const now = this.now();
      // A run generated ahead of time still bounds the next one.
      const next = nextRun(values, Math.max(now, current.lastRunAt ?? 0));
      return this.schedules.update(id, values, expectedRevision, next, now);
    })();
  }

  due(actor: Principal, query: unknown): DigestSchedule[] {
    this.access.require(actor, "case_admin");
    const parsed = dueSchema.parse(query);
    return this.schedules.due(actor.project, parsed.at ?? this.now(), parsed.limit);
  }

  /** Summarize the period since the schedule's last run, store it, and advance the schedule. */
  generate(actor: Principal, id: string, input: unknown): { digest: Digest; schedule: DigestSchedule } {
    this.access.require(actor, readAccess);
    const parsed = generateSchema.parse(input);
    return this.db.transaction(() => {
      const schedule = this.schedules.require(id);
      if (schedule.project !== actor.project) missing("digest schedule", id);
      if (schedule.principal !== actor.id) this.access.require(actor, "case_admin");
      if (!schedule.enabled) conflict("digest schedule is disabled");
      const { principal, project } = schedule;
      if (!this.grants.has({ id: principal, project }, readAccess)) conflict("schedule owner can no longer read the project");
      const at = parsed.at ?? this.now();
      const from = schedule.lastRunAt ?? schedule.createdAt;
      if (at <= from) conflict("digest period is empty", { from, at });
      const content = JSON.stringify(this.summarize(project, from, at));
      const now = this.now();
      const stored = this.digests.create({
        scheduleId: schedule.id,
        principal,
        project,
        periodStart: from,
        periodEnd: at,
        content,
        checksum: checksum(content),
        generatedBy: actor.id,
      }, now);
      return {
        digest: view(stored),
        schedule: this.schedules.advance(id, at, nextRun(schedule, at), now),
      };
    })();
  }

  listDigests(actor: Principal, query: unknown): Page<Digest> {
    this.access.require(actor, readAccess);
    const parsed = digestPageSchema.parse(query);
    const page = this.digests.list(actor, parsed.limit, parsed.offset);
    return { ...page, items: page.items.map(view) };
  }

  /** A stored digest with a check that its content still matches the recorded checksum. */
  getDigest(actor: Principal, id: unknown): Digest & { verified: boolean } {
    this.access.require(actor, readAccess);
    const digestId = digestIdSchema.parse(id);
    const stored = this.digests.require(digestId);
    if (stored.project !== actor.project || stored.principal !== actor.id) missing("digest", String(digestId));
    return { ...view(stored), verified: matchesChecksum(stored.content, stored.checksum) };
  }

  private summarize(project: string, from: number, to: number): DigestContent {
    const activity = this.digests.activity(project, from, to);
    return {
      jobs: { created: activity.created, changed: activity.changed },
      transitions: stages.map(stage => ({
        stage,
        label: stageLabel(stage),
        count: activity.transitions.get(stage) ?? 0,
      })),
      evidence: kinds.map(kind => ({
        kind,
        label: evidenceKindLabel(kind),
        count: activity.evidence.get(kind) ?? 0,
      })),
    };
  }

  private ownSchedule(actor: Principal, id: string): DigestSchedule {
    const schedule = this.schedules.require(id);
    if (schedule.project !== actor.project || schedule.principal !== actor.id) missing("digest schedule", id);
    return schedule;
  }
}
