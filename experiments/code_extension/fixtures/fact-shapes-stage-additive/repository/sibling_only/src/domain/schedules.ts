/** Wall-clock recurrences in a fixed UTC offset; callers supply every instant. */
export const cadences = ["daily", "weekly"] as const;
export type Cadence = (typeof cadences)[number];

export interface Recurrence {
  cadence: Cadence;
  /** 0 is Sunday; present exactly when the cadence is weekly. */
  weekday: number | null;
  hour: number;
  utcOffsetMinutes: number;
}

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const WEEK_MS = 7 * DAY_MS;

/** The first run strictly after `after`. */
export function nextRun(recurrence: Recurrence, after: number): number {
  const offset = recurrence.utcOffsetMinutes * MINUTE_MS;
  // Shift into local wall time so day boundaries fall at local midnight.
  const local = after + offset;
  const midnight = Math.floor(local / DAY_MS) * DAY_MS;
  let candidate = midnight + recurrence.hour * HOUR_MS;
  if (recurrence.cadence === "weekly") {
    const today = new Date(midnight).getUTCDay();
    candidate += ((recurrence.weekday! - today + 7) % 7) * DAY_MS;
  }
  if (candidate <= local) candidate += recurrence.cadence === "weekly" ? WEEK_MS : DAY_MS;
  return candidate - offset;
}
