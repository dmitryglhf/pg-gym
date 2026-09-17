import { activityState, ageLabel, ageSeconds } from "../lib/activity.ts";

function assert(value: unknown, message = "Assertion failed"): asserts value {
  if (!value) throw new Error(message);
}

Deno.test("fresh transport does not disguise quiet model output, and stale transport is distinct", () => {
  const quiet = activityState({
    now: 90000,
    startedAt: 1000,
    contactAt: 89000,
    progressAt: 2000,
    trackContact: true,
  });
  assert(quiet.quiet && !quiet.stale);
  const stale = activityState({
    now: 90000,
    startedAt: 1000,
    contactAt: 2000,
    progressAt: 88000,
    trackContact: true,
  });
  assert(stale.stale && !stale.quiet);
  assert(activityState({ now: 1000, disconnected: true }).stale);
  assert(ageSeconds("invalid", 5000) === null);
  assert(
    ageSeconds(6000, 5000) === 0,
    "Clock skew must not show negative durations",
  );
  assert(ageLabel(null, 5000) === "not yet received");
});

Deno.test("a queued job is neither quiet nor stale however long it waits", () => {
  const waiting = activityState({
    now: 900000,
    startedAt: 1000,
    contactAt: 1000,
    progressAt: 1000,
    trackContact: true,
    queued: true,
  });
  assert(!waiting.quiet && !waiting.stale);
  assert(waiting.elapsed === 899, "queue time is still shown");
});
