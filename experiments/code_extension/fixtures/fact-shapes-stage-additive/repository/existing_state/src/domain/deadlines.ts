/**
 * Escalation ages are whole minutes between a job's last update and an evaluation time.
 * Callers pass both instants; nothing here reads a clock.
 */
export const MINUTE_MS = 60_000;

export function ageInMinutes(since: number, at: number): number {
  return at <= since ? 0 : Math.floor((at - since) / MINUTE_MS);
}

/** The last instant at which a job updated at `since` is still within its limit. */
export function deadline(since: number, maxAgeMinutes: number): number {
  return since + maxAgeMinutes * MINUTE_MS;
}

/** Jobs updated strictly before this instant have exceeded the limit at `at`. */
export function staleBefore(at: number, maxAgeMinutes: number): number {
  return at - maxAgeMinutes * MINUTE_MS;
}
