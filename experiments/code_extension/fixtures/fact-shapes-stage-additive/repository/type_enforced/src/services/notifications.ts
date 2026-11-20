import type { Principal } from "../domain/models.ts";
import { readAccess } from "../domain/access_levels.ts";
import { inboxSchema, markReadSchema, type Notification } from "../domain/notifications.ts";
import { NotificationRepository } from "../repositories/notifications.ts";
import { AccessService } from "./access.ts";

export class NotificationService {
  constructor(
    private readonly notifications: NotificationRepository,
    private readonly access: AccessService,
    private readonly now: () => number,
  ) {}

  inbox(actor: Principal, input: unknown): Notification[] {
    this.access.require(actor, readAccess);
    const query = inboxSchema.parse(input);
    return this.notifications.inbox(actor, query.unread, query.limit);
  }

  markRead(actor: Principal, input: unknown): { marked: number } {
    this.access.require(actor, readAccess);
    const { ids } = markReadSchema.parse(input);
    return { marked: this.notifications.markRead(actor, ids, this.now()) };
  }

  counts(actor: Principal) {
    this.access.require(actor, readAccess);
    const actions = this.notifications.countsByAction(actor);
    return { unread: actions.reduce((sum, row) => sum + row.unread, 0), actions };
  }
}
