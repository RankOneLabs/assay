import type { Stage } from "../../stage/types.ts";
import type { EvidenceKind } from "../../evidence_kind/types.ts";
import type { RoutePermission } from "../../route_permission/types.ts";
import { conflict } from "./errors.ts";

/** Each stage requires a deliberate transition rule when the vocabulary grows. */
const successors: Record<Stage, readonly Stage[]> = {
  queued: ["active"],
  active: ["queued", "complete"],
  complete: [],
};

export function canTransition(from: Stage, to: Stage): boolean {
  return successors[from].includes(to);
}

export function requireTransition(from: Stage, to: Stage): void {
  if (!canTransition(from, to)) {
    conflict(`cannot move from ${from} to ${to}`);
  }
}

export const evidenceMedia: Record<EvidenceKind, string> = {
  document: "text/plain",
  image: "image/png",
  testimony: "text/markdown",
};

export const permissionDescriptions: Record<RoutePermission, string> = {
  case_read: "Read jobs, evidence and reports in a project",
  case_write: "Create jobs and change evidence in a project",
  case_admin: "Manage grants, archive jobs and purge records",
};

export function mediaFor(kind: EvidenceKind): string {
  return evidenceMedia[kind];
}

export function permissionDescription(permission: RoutePermission): string {
  return permissionDescriptions[permission];
}
