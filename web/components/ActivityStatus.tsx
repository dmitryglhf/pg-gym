import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";
import { activityState, ageLabel, elapsedLabel } from "@/lib/activity.ts";
import type { ActivityTime } from "@/lib/activity.ts";

/** The clock is only a duration display. It is never a heartbeat. */
export function useActivityClock(active = true) {
  const [now, setNow] = useState(0);
  useEffect(() => {
    setNow(Date.now());
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

export function ProgressRing({ paused = false }: { paused?: boolean }) {
  return (
    <svg
      class={`progress-ring${paused ? " is-paused" : ""}`}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <circle class="progress-ring-track" cx="12" cy="12" r="9" />
      <circle class="progress-ring-arc" cx="12" cy="12" r="9" />
    </svg>
  );
}

export function ActivityStatus(props: {
  title: string;
  now: number;
  startedAt?: ActivityTime;
  contact?: { label: string; at: ActivityTime };
  progress?: { label: string; at: ActivityTime };
  disconnected?: boolean;
  staleAfter?: number;
  quietAfter?: number;
  quietMessage?: string;
  note?: string;
  actions?: ComponentChildren;
  compact?: boolean;
  queued?: boolean;
}) {
  const state = activityState({
    now: props.now,
    startedAt: props.startedAt,
    contactAt: props.contact?.at,
    progressAt: props.progress?.at,
    trackContact: !!props.contact,
    disconnected: props.disconnected,
    staleAfter: props.staleAfter,
    quietAfter: props.quietAfter,
  });
  const warning = state.stale ? "Updates interrupted" : null;
  return (
    <div
      class={`activity-status${props.compact ? " activity-compact" : ""}${
        state.stale ? " activity-stale" : ""
      }`}
    >
      <ProgressRing paused={state.stale || props.queued} />
      <div class="activity-content">
        <div class="activity-heading">
          <strong role="status">{warning ?? props.title}</strong>
          {state.elapsed !== null && (
            <span
              class="activity-elapsed"
              aria-live="off"
              title="Elapsed time; does not confirm worker progress"
            >
              {elapsedLabel(state.elapsed)}
            </span>
          )}
        </div>
        {(props.contact || props.progress) && (
          <div class="activity-freshness" aria-live="off">
            {props.contact && (
              <span>
                {props.contact.label} · {ageLabel(props.contact.at, props.now)}
              </span>
            )}
            {props.progress && (
              <span>
                {props.progress.label} ·{" "}
                {ageLabel(props.progress.at, props.now)}
              </span>
            )}
          </div>
        )}
        <p class="activity-note" role="status">
          {state.stale
            ? `Last reported: ${props.title}. Current progress is unknown.`
            : state.quiet && props.quietMessage
            ? props.quietMessage
            : props.note}
        </p>
      </div>
      {props.actions && <div class="activity-actions">{props.actions}</div>}
    </div>
  );
}
