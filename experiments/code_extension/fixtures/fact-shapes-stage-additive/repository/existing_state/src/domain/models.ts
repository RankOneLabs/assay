import type { Stage } from "../../stage/types.ts";
import type { EvidenceKind } from "../../evidence_kind/types.ts";
import type { RoutePermission } from "../../route_permission/types.ts";

export interface Job {
  id: string;
  title: string;
  description: string;
  stage: Stage;
  priority: number;
  owner: string;
  project: string;
  revision: number;
  createdAt: number;
  updatedAt: number;
  archivedAt: number | null;
  /** The run the job belongs to, if any. */
  runId: string | null;
  /** When the job last reached a done stage; null while it is not done. */
  finishedAt: number | null;
  /** What the job's attempts add up to, kept by the roll-up engine. */
  rollup: JobRollup;
}

/** A job's stored roll-up over its attempts. */
export interface JobRollup {
  attempts: number;
  running: boolean;
  outcome: "passed" | "failed" | null;
}

/** A run's stored roll-up over its jobs. */
export interface RunRollup {
  total: number;
  open: number;
  done: number;
  status: "running" | "finished";
}

/** A group of jobs that is followed as one. */
export interface Run {
  id: string;
  project: string;
  title: string;
  state: RunRollup;
  finishedAt: number | null;
  revision: number;
  createdAt: number;
  updatedAt: number;
}

export interface Evidence {
  id: string;
  jobId: string;
  kind: EvidenceKind;
  title: string;
  content: string;
  checksum: string;
  author: string;
  revision: number;
  createdAt: number;
  updatedAt: number;
}

export interface Grant {
  principal: string;
  permission: RoutePermission;
  project: string;
  grantedBy: string;
  createdAt: number;
}

export interface JobEvent {
  sequence: number;
  jobId: string;
  action: string;
  actor: string;
  detail: string;
  createdAt: number;
}

export interface Attempt {
  id: string;
  jobId: string;
  sessionId: string;
  worker: string;
  startedAt: number;
  finishedAt: number | null;
  exitCode: number | null;
  output: string;
}

export interface JobFilter {
  stage?: Stage;
  owner?: string;
  project?: string;
  query?: string;
  archived?: boolean;
  minPriority?: number;
  limit: number;
  offset: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  nextOffset: number | null;
}

export interface JobCreate {
  id: string;
  title: string;
  description: string;
  priority: number;
  owner: string;
  project: string;
  runId?: string;
}

export interface JobPatch {
  title?: string;
  description?: string;
  priority?: number;
  owner?: string;
  expectedRevision: number;
}

export interface EvidenceCreate {
  id: string;
  kind: EvidenceKind;
  title: string;
  content: string;
  author: string;
}

export interface EvidencePatch {
  title?: string;
  content?: string;
  expectedRevision: number;
}

export interface JobBundle {
  job: Job;
  evidence: Evidence[];
  events: JobEvent[];
  attempts: Attempt[];
}

export interface Principal {
  id: string;
  project: string;
}

export interface StageCount {
  stage: Stage;
  label: string;
  count: number;
}

export interface EvidenceCount {
  kind: EvidenceKind;
  label: string;
  count: number;
  bytes: number;
}

export interface PermissionCount {
  permission: RoutePermission;
  label: string;
  grants: number;
}

export interface Workload {
  owner: string;
  jobs: number;
  priority: number;
}

export interface Summary {
  total: number;
  archived: number;
  stages: StageCount[];
  evidence: EvidenceCount[];
  permissions: PermissionCount[];
  workloads: Workload[];
}
