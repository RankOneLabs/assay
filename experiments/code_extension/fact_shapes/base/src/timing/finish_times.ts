/**
 * Finish times shown in reports and used for durations. A run's finish time is the
 * moment its stored state became finished.
 */
export function runFinishTime(recorded: number | null, finished: boolean, now: number): number | null {
  return finished ? recorded ?? now : null;
}

/** Milliseconds between two times, or null while the second is unknown. */
export function durationBetween(startedAt: number, finishedAt: number | null): number | null {
  return finishedAt === null ? null : Math.max(0, finishedAt - startedAt);
}
