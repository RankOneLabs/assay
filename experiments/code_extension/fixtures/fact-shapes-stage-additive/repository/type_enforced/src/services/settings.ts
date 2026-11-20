import type { Database } from "bun:sqlite";
import type { Principal } from "../domain/models.ts";
import { readAccess } from "../domain/access_levels.ts";
import { invalid, revisionMatches } from "../domain/errors.ts";
import {
  applySettings, settingsPatchSchema, type ProjectSettings, type SettingsHistoryEntry,
} from "../domain/settings.ts";
import { SettingsRepository } from "../repositories/settings.ts";
import { GrantRepository } from "../repositories/grants.ts";
import { AccessService } from "./access.ts";

/** Project settings are reported by the usage service; existing operations do not enforce them. */
export class SettingsService {
  constructor(
    private readonly db: Database,
    private readonly settings: SettingsRepository,
    private readonly grants: GrantRepository,
    private readonly access: AccessService,
    private readonly now: () => number,
  ) {}

  get(actor: Principal): ProjectSettings {
    this.access.require(actor, readAccess);
    return this.settings.get(actor.project);
  }

  /** A change that leaves every value as it was returns the current record without a revision. */
  update(actor: Principal, input: unknown): ProjectSettings {
    this.access.require(actor, "case_admin");
    const parsed = settingsPatchSchema.parse(input);
    return this.db.transaction(() => {
      const current = this.settings.get(actor.project);
      revisionMatches(current.revision, parsed.expectedRevision);
      const { next, changes } = applySettings(current, parsed);
      if (!changes.length) return current;
      const reviewer = next.defaultReviewOwner;
      if (
        reviewer !== null && reviewer !== current.defaultReviewOwner &&
        !this.grants.has({ id: reviewer, project: actor.project }, "case_write")
      ) invalid(`default review owner ${reviewer} needs write permission in the project`);
      const now = this.now();
      const saved = this.settings.save(actor.project, next, parsed.expectedRevision, actor.id, now);
      this.settings.appendHistory(actor.project, saved.revision, actor.id, changes, parsed.reason ?? null, now);
      return saved;
    })();
  }

  history(actor: Principal, after: number, limit: number): SettingsHistoryEntry[] {
    this.access.require(actor, readAccess);
    return this.settings.history(actor.project, after, limit);
  }
}
