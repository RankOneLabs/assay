import { StoredEvidenceKind } from "./preferences/evidence_kind_defaults.ts";
import { StoredRoutePermission } from "./preferences/route_permission_defaults.ts";
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

  constructor(input: unknown = {}, now: () => number = Date.now, database?: Database) {
    this.config = loadConfig(input);
    this.db = database ?? new Database(this.config.databasePath);
    initializeDatabase(this.db, baseMigrations());
    this.jobRepository = new JobRepository(this.db);
    this.evidenceRepository = new EvidenceRepository(this.db);
    this.eventRepository = new EventRepository(this.db);
    this.grantRepository = new GrantRepository(this.db);
    this.attemptRepository = new AttemptRepository(this.db);
    this.sessions = new SessionService();
    this.access = new AccessService(this.grantRepository, now, new StoredRoutePermission(), this.db);
    this.jobs = new JobService(
      this.db, this.jobRepository, this.eventRepository, this.access, this.config, now,
      jobId => this.attemptRepository.list(jobId)
        .filter(attempt => this.sessions.isBuildRunning(attempt.sessionId))
        .map(attempt => attempt.sessionId),
    );
    this.evidence = new EvidenceService(
      this.db, this.evidenceRepository, this.jobRepository, this.eventRepository,
      this.access, this.jobs, this.config, now, new StoredEvidenceKind(),
    );
    this.builds = new BuildService(
      this.db, this.jobRepository, this.attemptRepository, this.eventRepository,
      this.sessions, this.access, now,
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
  }

  /** Callers own the context and close it after outstanding synchronous operations. */
  close(): void {
    this.db.close();
  }

  [Symbol.dispose](): void {
    this.close();
  }
}
