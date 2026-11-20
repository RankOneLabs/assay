import { StoredEvidenceKind, StoredRoutePermission } from "./preferences/defaults.ts";
import { Database } from "bun:sqlite";
import type { Config } from "./config.ts";
import { loadConfig } from "./config.ts";
import { baseMigrations, initializeDatabase } from "./database.ts";
import { JobRepository } from "./repositories/jobs.ts";
import { EvidenceRepository } from "./repositories/evidence.ts";
import { EventRepository } from "./repositories/events.ts";
import { GrantRepository } from "./repositories/grants.ts";
import { AttemptRepository } from "./repositories/attempts.ts";
import { SessionService } from "./sessions/session_service.ts";
import { AccessService } from "./services/access.ts";
import { JobService } from "./services/jobs.ts";
import { EvidenceService } from "./services/evidence.ts";
import { BuildService } from "./services/builds.ts";
import { ReportService } from "./services/reports.ts";
import { ExportService } from "./services/exports.ts";
import { ImportService } from "./services/imports.ts";
import { DispatchService } from "./services/dispatch.ts";
import { PlanningService } from "./services/planning.ts";
import { DependencyRepository } from "./repositories/dependencies.ts";
import { MaintenanceService } from "./services/maintenance.ts";
import { CommentRepository } from "./repositories/comments.ts";
import { CommentService } from "./services/comments.ts";
import { AuditRepository } from "./repositories/audit.ts";
import { AuditService } from "./services/audit.ts";
import { TagRepository } from "./repositories/tags.ts";
import { SavedSearchRepository } from "./repositories/searches.ts";
import { SettingsRepository } from "./repositories/settings.ts";
import { TagService } from "./services/tags.ts";
import { SearchService } from "./services/searches.ts";
import { SettingsService } from "./services/settings.ts";
import { UsageService } from "./services/usage.ts";
import { EscalationRuleRepository } from "./repositories/escalation_rules.ts";
import { EscalationRepository } from "./repositories/escalations.ts";
import { EscalationService } from "./services/escalations.ts";
import { DigestScheduleRepository } from "./repositories/digest_schedules.ts";
import { DigestRepository } from "./repositories/digests.ts";
import { DigestService } from "./services/digests.ts";
import { SubscriptionRepository } from "./repositories/subscriptions.ts";
import { WebhookRepository } from "./repositories/webhooks.ts";
import { DeliveryRepository } from "./repositories/deliveries.ts";
import { NotificationRepository } from "./repositories/notifications.ts";
import { OutboxRepository } from "./repositories/outbox.ts";
import { SubscriptionService } from "./services/subscriptions.ts";
import { WebhookService } from "./services/webhooks.ts";
import { OutboxService } from "./services/outbox.ts";
import { NotificationService } from "./services/notifications.ts";
import { RunRepository } from "./repositories/runs.ts";
import { RunService } from "./services/runs.ts";
import { RunSummaries } from "./services/run_summaries.ts";
import { RollupEngine } from "./rollup/engine.ts";
import { jobRollup, runRollup } from "./rollup/declarations.ts";

/** Dependency assembly has references to owners, never a copy of their data. */
export class ServiceContext {
  readonly config: Config;
  readonly db: Database;
  readonly jobRepository: JobRepository;
  readonly evidenceRepository: EvidenceRepository;
  readonly eventRepository: EventRepository;
  readonly grantRepository: GrantRepository;
  readonly attemptRepository: AttemptRepository;
  readonly sessions: SessionService;
  readonly access: AccessService;
  readonly jobs: JobService;
  readonly evidence: EvidenceService;
  readonly builds: BuildService;
  readonly reports: ReportService;
  readonly exports: ExportService;
  readonly imports: ImportService;
  readonly dispatch: DispatchService;
  readonly planning: PlanningService;
  readonly maintenance: MaintenanceService;
  readonly comments: CommentService;
  readonly audit: AuditService;
  readonly tags: TagService;
  readonly searches: SearchService;
  readonly settings: SettingsService;
  readonly usage: UsageService;
  readonly escalations: EscalationService;
  readonly digests: DigestService;
  readonly subscriptions: SubscriptionService;
  readonly webhooks: WebhookService;
  readonly outbox: OutboxService;
  readonly notifications: NotificationService;
  readonly runRepository: RunRepository;
  readonly rollups: RollupEngine;
  readonly runs: RunService;

  constructor(input: unknown = {}, now: () => number = Date.now, database?: Database) {
    this.config = loadConfig(input);
    this.db = database ?? new Database(this.config.databasePath);
    initializeDatabase(this.db, baseMigrations());
    this.jobRepository = new JobRepository(this.db);
    this.evidenceRepository = new EvidenceRepository(this.db);
    this.eventRepository = new EventRepository(this.db);
    this.grantRepository = new GrantRepository(this.db);
    this.attemptRepository = new AttemptRepository(this.db);
    this.runRepository = new RunRepository(this.db);
    this.rollups = new RollupEngine();
    this.rollups.leaf("attempt", id => ({ level: "job", id: this.attemptRepository.require(id).jobId }));
    this.rollups.level("job", {
      rollup: jobRollup,
      children: id => this.attemptRepository.list(id),
      stored: id => this.jobRepository.require(id).rollup,
      store: (id, state) => this.jobRepository.storeRollup(id, state),
      parent: id => {
        const runId = this.jobRepository.require(id).runId;
        return runId === null ? null : { level: "run", id: runId };
      },
    });
    this.rollups.level("run", {
      rollup: runRollup,
      children: id => this.jobRepository.inRun(id),
      stored: id => this.runRepository.require(id).state,
      store: (id, state) => { this.runRepository.store(id, state, now()); },
      parent: () => null,
    });
    this.sessions = new SessionService();
    this.access = new AccessService(this.grantRepository, now, new StoredRoutePermission(), this.db);
    this.jobs = new JobService(
      this.db, this.jobRepository, this.eventRepository, this.access, this.config, now,
      jobId => this.attemptRepository.list(jobId)
        .filter(attempt => this.sessions.isBuildRunning(attempt.sessionId))
        .map(attempt => attempt.sessionId),
      this.runRepository, this.rollups,
    );
    this.evidence = new EvidenceService(
      this.db, this.evidenceRepository, this.jobRepository, this.eventRepository,
      this.access, this.jobs, this.config, now, new StoredEvidenceKind(),
    );
    this.builds = new BuildService(
      this.db, this.jobRepository, this.attemptRepository, this.eventRepository,
      this.sessions, this.access, now, this.rollups,
    );
    this.reports = new ReportService(this.db, this.access);
    this.exports = new ExportService(
      this.db, this.jobRepository, this.evidenceRepository, this.eventRepository,
      this.attemptRepository, this.access, this.config, now,
    );
    this.planning = new PlanningService(
      this.db, this.jobRepository, new DependencyRepository(this.db), this.eventRepository,
      this.access, this.jobs, now,
    );
    this.imports = new ImportService(
      this.db, this.jobs, this.evidence, this.access, this.jobRepository,
      this.evidenceRepository, this.config,
    );
    this.dispatch = new DispatchService(
      this.planning, this.builds, this.access, this.jobRepository,
      this.attemptRepository, this.sessions, this.config,
    );
    this.maintenance = new MaintenanceService(
      this.db, this.jobRepository, this.eventRepository, this.evidenceRepository,
      this.attemptRepository, this.sessions, this.access, this.config, now,
      new DependencyRepository(this.db),
    );
    this.comments = new CommentService(
      this.db, new CommentRepository(this.db), this.jobRepository, this.eventRepository,
      this.grantRepository, this.access, this.jobs, now,
    );
    this.audit = new AuditService(new AuditRepository(this.db), this.jobRepository, this.access, now);
    const tagRepository = new TagRepository(this.db);
    this.tags = new TagService(
      this.db, tagRepository, this.jobRepository, this.jobs, this.eventRepository, this.access, now,
    );
    this.searches = new SearchService(
      this.db, new SavedSearchRepository(this.db), tagRepository, this.jobRepository, this.access, now,
    );
    const settingsRepository = new SettingsRepository(this.db);
    this.settings = new SettingsService(this.db, settingsRepository, this.grantRepository, this.access, now);
    this.usage = new UsageService(this.db, settingsRepository, this.access, now);
    this.escalations = new EscalationService(
      this.db, new EscalationRuleRepository(this.db), new EscalationRepository(this.db),
      this.eventRepository, this.grantRepository, this.access, now,
    );
    this.digests = new DigestService(
      this.db, new DigestScheduleRepository(this.db), new DigestRepository(this.db),
      this.grantRepository, this.access, now,
    );
    const subscriptionRepository = new SubscriptionRepository(this.db);
    const webhookRepository = new WebhookRepository(this.db);
    const notificationRepository = new NotificationRepository(this.db);
    this.subscriptions = new SubscriptionService(
      this.db, subscriptionRepository, this.jobRepository, this.access, now,
    );
    this.webhooks = new WebhookService(this.db, webhookRepository, this.access, now);
    this.outbox = new OutboxService(
      this.db, new OutboxRepository(this.db), new DeliveryRepository(this.db), notificationRepository,
      subscriptionRepository, webhookRepository, this.grantRepository, this.access, now,
    );
    this.notifications = new NotificationService(notificationRepository, this.access, now);
    this.runs = new RunService(
      this.db, this.runRepository, this.jobRepository, this.eventRepository,
      new RunSummaries(this.db, this.jobRepository, this.attemptRepository, now),
      this.rollups, this.access, now,
    );
  }

  /** Callers own the context and close it after outstanding synchronous operations. */
  close(): void {
    this.db.close();
  }

  [Symbol.dispose](): void {
    this.close();
  }
}
