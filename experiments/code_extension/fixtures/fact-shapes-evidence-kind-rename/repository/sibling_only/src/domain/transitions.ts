import { values as stages, type Stage } from "../../stage/types.ts";
import type { EvidenceKind } from "../../evidence_kind/types.ts";
import type { RoutePermission } from "../../route_permission/types.ts";
import { vocabularyStore } from "../vocabulary.ts";
import { conflict } from "./errors.ts";

export function canTransition(from: Stage, to: Stage): boolean {
  const source = stages.indexOf(from);
  const target = stages.indexOf(to);
  return source === 0 ? target === 1 : source === 1 && (target === 0 || target === 2);
}
export function requireTransition(from: Stage, to: Stage): void {
  if (!canTransition(from, to)) conflict(`cannot move from ${from} to ${to}`);
}
export const evidenceMedia = vocabularyStore.record("evidence_kind", (_value, index) =>
  ["text/plain", "image/png", "text/markdown"][index] ?? "application/octet-stream",
);
export const permissionDescriptions = vocabularyStore.record("route_permission", (_value, index) => [
  "Read jobs, evidence and reports in a project",
  "Create jobs and change evidence in a project",
  "Manage grants, archive jobs and purge records",
][index] ?? "Additional project permission");
export function mediaFor(kind: EvidenceKind): string { return evidenceMedia[kind]; }
export function permissionDescription(permission: RoutePermission): string {
  return permissionDescriptions[permission];
}
