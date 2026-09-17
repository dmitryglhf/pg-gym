/** Receipt time and progress time are deliberately independent. */
export type ActivityTime = string | number | null | undefined;

export function timestamp(value: ActivityTime): number | null {
  const n = typeof value === "string" ? Date.parse(value) : value;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

export function ageSeconds(at: ActivityTime, now: number): number | null {
  const time = timestamp(at);
  return time === null || !now
    ? null
    : Math.max(0, Math.floor((now - time) / 1000));
}

export function elapsedLabel(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m`;
}

export function ageLabel(at: ActivityTime, now: number): string {
  const age = ageSeconds(at, now);
  return age === null
    ? "not yet received"
    : age < 2
    ? "just now"
    : `${elapsedLabel(age)} ago`;
}

export function activityState(input: {
  now: number;
  startedAt?: ActivityTime;
  contactAt?: ActivityTime;
  progressAt?: ActivityTime;
  trackContact?: boolean;
  disconnected?: boolean;
  staleAfter?: number;
  quietAfter?: number;
  /** Nothing has started: waiting is neither stale nor quiet. */
  queued?: boolean;
}) {
  const elapsed = ageSeconds(input.startedAt, input.now);
  const contactAge = ageSeconds(input.contactAt, input.now);
  const progressAge = ageSeconds(
    input.progressAt ?? input.startedAt,
    input.now,
  );
  const stale = !input.queued && (!!input.disconnected ||
    !!input.trackContact &&
      (contactAge ?? elapsed ?? 0) >= (input.staleAfter ?? 30));
  return {
    elapsed,
    stale,
    quiet: !input.queued && !stale && progressAge !== null &&
      progressAge >= (input.quietAfter ?? 60),
    progressAge,
  };
}
