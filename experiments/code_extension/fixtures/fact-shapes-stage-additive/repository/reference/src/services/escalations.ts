import type { Database } from "bun:sqlite";
import { values as stages } from "../../stage/types.ts";
import type { Page, Principal } from "../domain/models.ts";
import { readAccess } from "../domain/access_levels.ts";
import { conflict, forbidden, invalid, limitExceeded } from "../domain/errors.ts";
import { ageInMinutes, deadline, staleBefore } from "../domain/deadlines.ts";
import {
  escalationFilterSchema, escalationIdSchema, evaluationSchema, resolutionSchema,
  ruleFilterSchema, rulePatchSchema, ruleSchema,
} from "../domain/escalation_validation.ts";
import { stageLabel } from "../presentation/labels.ts";
import { EscalationRuleRepository, type EscalationRule } from "../repositories/escalation_rules.ts";
import { EscalationRepository, type Escalation } from "../repositories/escalations.ts";
import { EventRepository } from "../repositories/events.ts";
import { GrantRepository } from "../repositories/grants.ts";
import { AccessService } from "./access.ts";

const MAX_RULES_PER_PROJECT = 50;
const MAX_OPENED_PER_PASS = 200;

export class EscalationService {
  constructor(
    private readonly db: Database,
    private readonly rules: EscalationRuleRepository,
    private readonly escalations: EscalationRepository,
    private readonly events: EventRepository,
    private readonly grants: GrantRepository,
    private readonly access: AccessService,
    private readonly now: () => number,
  ) {}

  createRule(actor: Principal, input: unknown): EscalationRule {
    this.access.require(actor, "case_admin");
    const { id, ...values } = ruleSchema.parse(input);
    this.requireReachable(actor.project, values.target);
    return this.db.transaction(() => {
      if (this.rules.count(actor.project) >= MAX_RULES_PER_PROJECT) {
        limitExceeded("project escalation rule limit reached");
      }
      return this.rules.create(id, actor.project, values, actor.id, this.now());
    })();
  }

  listRules(actor: Principal, query: unknown): EscalationRule[] {
    this.access.require(actor, readAccess);
    return this.rules.list(actor.project, ruleFilterSchema.parse(query));
  }

  getRule(actor: Principal, id: string): EscalationRule {
    this.access.require(actor, readAccess);
    return this.projectRule(actor, id);
  }

  updateRule(actor: Principal, id: string, input: unknown): EscalationRule {
    this.access.require(actor, "case_admin");
    const { expectedRevision, ...changes } = rulePatchSchema.parse(input);
    if (changes.target !== undefined) this.requireReachable(actor.project, changes.target);
    return this.db.transaction(() => {
      const current = this.projectRule(actor, id);
      return this.rules.update(id, {
        stage: changes.stage ?? current.stage,
        maxAgeMinutes: changes.maxAgeMinutes ?? current.maxAgeMinutes,
        minPriority: changes.minPriority ?? current.minPriority,
        target: changes.target ?? current.target,
        enabled: changes.enabled ?? current.enabled,
      }, expectedRevision, this.now());
    })();
  }

  /** Resolve escalations whose job moved on, then open one per stale job and enabled rule. */
  evaluate(actor: Principal, input: unknown) {
    this.access.require(actor, "case_admin");
    const at = evaluationSchema.parse(input).at ?? this.now();
    return this.db.transaction(() => {
      const resolved = this.escalations.departed(actor.project).map(escalation =>
        this.close(escalation, actor.id, "job left the escalated stage", at, true),
      );
      const opened: Escalation[] = [];
      let truncated = false;
      for (const rule of this.rules.list(actor.project, { enabled: true })) {
        const room = MAX_OPENED_PER_PASS - opened.length;
        const stale = this.escalations.stale(rule, staleBefore(at, rule.maxAgeMinutes), room + 1);
        if (stale.length > room) truncated = true;
        for (const job of stale.slice(0, room)) {
          const escalation = this.escalations.open(rule, job.id, ageInMinutes(job.updatedAt, at), at);
          this.events.append(job.id, "job.escalated", actor.id, {
            escalationId: escalation.id,
            ruleId: rule.id,
            target: rule.target,
            ageMinutes: escalation.ageMinutes,
            deadline: deadline(job.updatedAt, rule.maxAgeMinutes),
          }, at);
          opened.push(escalation);
        }
      }
      return { at, opened, resolved, truncated };
    })();
  }

  listOpen(actor: Principal, query: unknown): Page<Escalation> {
    this.access.require(actor, readAccess);
    return this.escalations.listOpen(actor.project, escalationFilterSchema.parse(query));
  }

  get(actor: Principal, id: unknown): Escalation {
    this.access.require(actor, readAccess);
    return this.projectEscalation(actor, id);
  }

  acknowledge(actor: Principal, id: unknown): Escalation {
    this.access.require(actor, readAccess);
    return this.db.transaction(() => {
      const current = this.projectEscalation(actor, id);
      this.requireHandler(actor, current);
      if (current.resolvedAt !== null) conflict("escalation is already resolved");
      if (current.acknowledgedAt !== null) conflict("escalation is already acknowledged");
      const now = this.now();
      const escalation = this.escalations.acknowledge(current.id, actor.id, now);
      this.events.append(escalation.jobId, "job.escalation_acknowledged", actor.id, {
        escalationId: escalation.id,
        ruleId: escalation.ruleId,
      }, now);
      return escalation;
    })();
  }

  resolve(actor: Principal, id: unknown, input: unknown): Escalation {
    this.access.require(actor, readAccess);
    const { note } = resolutionSchema.parse(input);
    return this.db.transaction(() => {
      const current = this.projectEscalation(actor, id);
      this.requireHandler(actor, current);
      if (current.resolvedAt !== null) conflict("escalation is already resolved");
      return this.close(current, actor.id, note, this.now(), false);
    })();
  }

  summary(actor: Principal) {
    this.access.require(actor, readAccess);
    const open = this.escalations.openByStage(actor.project);
    const enabled = this.rules.list(actor.project, { enabled: true });
    return stages.map(stage => ({
      stage,
      label: stageLabel(stage),
      rules: enabled.filter(rule => rule.stage === stage).length,
      open: open.get(stage)?.open ?? 0,
      acknowledged: open.get(stage)?.acknowledged ?? 0,
      oldestOpenedAt: open.get(stage)?.oldestOpenedAt ?? null,
    }));
  }

  private close(escalation: Escalation, actor: string, note: string, at: number, automatic: boolean): Escalation {
    const resolved = this.escalations.resolve(escalation.id, actor, note, at);
    this.events.append(resolved.jobId, "job.escalation_resolved", actor, {
      escalationId: resolved.id,
      ruleId: resolved.ruleId,
      automatic,
      note,
    }, at);
    return resolved;
  }

  private projectRule(actor: Principal, id: string): EscalationRule {
    const rule = this.rules.require(id);
    if (rule.project !== actor.project) forbidden("escalation rule belongs to another project");
    return rule;
  }

  private projectEscalation(actor: Principal, id: unknown): Escalation {
    const escalation = this.escalations.require(escalationIdSchema.parse(id));
    if (escalation.project !== actor.project) forbidden("escalation belongs to another project");
    return escalation;
  }

  /** The escalated principal handles its own escalations; anyone else needs write access. */
  private requireHandler(actor: Principal, escalation: Escalation): void {
    if (escalation.target !== actor.id) this.access.require(actor, "case_write");
  }

  private requireReachable(project: string, target: string): void {
    if (!this.grants.has({ id: target, project }, readAccess)) invalid("escalation target cannot read this project");
  }
}
