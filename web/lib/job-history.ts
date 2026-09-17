import { useEffect, useRef, useState } from "preact/hooks";
import { api, message, terminal } from "./platform.ts";
import type { Job } from "./platform.ts";

/** Keep already seen rows when the rolling first page moves forward. */
export function mergeJobs(current: Job[], incoming: Job[]) {
  if (!incoming.length) return current;
  const byId = new Map(current.map((job) => [job.id, job]));
  for (const job of incoming) {
    if ((byId.get(job.id)?.updated_at ?? 0) <= job.updated_at) {
      byId.set(job.id, job);
    }
  }
  return [...byId.values()].sort((a, b) =>
    b.created_at - a.created_at || b.id.localeCompare(a.id)
  );
}
export function useJobHistory(recent: Job[] | null, next: string | null) {
  const [history, setHistory] = useState<
    { items: Job[]; cursor: string | null; initialized: boolean }
  >({ items: [], cursor: null, initialized: false });
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [statusError, setStatusError] = useState("");
  const snapshot = useRef(history),
    offset = useRef(0),
    refreshing = useRef(false);
  snapshot.current = history;
  const lock = useRef(false), alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!recent) return;
    setHistory((old) => {
      const known = new Set(old.items.map((job) => job.id));
      // A suspended tab may miss more than one page. Rewind pagination to fill that gap.
      const gap = next && recent.length &&
        !recent.some((job) => known.has(job.id));
      return {
        items: mergeJobs(old.items, recent),
        cursor: old.initialized && !gap ? old.cursor : next,
        initialized: true,
      };
    });
  }, [recent, next]);
  useEffect(() => {
    if (!recent || refreshing.current) return;
    const head = new Set(recent.map((job) => job.id));
    const active = snapshot.current.items.filter((job) =>
      !head.has(job.id) && !terminal(job)
    );
    if (!active.length) {
      setStatusError("");
      return;
    }
    // Bound requests for large histories; rotate through older active runs.
    const start = offset.current % active.length;
    const batch = [...active.slice(start), ...active.slice(0, start)].slice(
      0,
      10,
    );
    offset.current = start + batch.length;
    refreshing.current = true;
    Promise.allSettled(
      batch.map((job) => api<Job>("/jobs/" + encodeURIComponent(job.id))),
    ).then((results) => {
      if (!alive.current) return;
      const updated = results.flatMap((result) =>
        result.status === "fulfilled" ? [result.value] : []
      );
      setHistory((old) => ({ ...old, items: mergeJobs(old.items, updated) }));
      setStatusError(
        results.some((result) => result.status === "rejected")
          ? "Some older active runs could not be refreshed. Their last known states are shown; retrying automatically."
          : "",
      );
    }).finally(() => {
      refreshing.current = false;
    });
  }, [recent]);
  async function loadOlder() {
    const cursor = history.cursor;
    if (!cursor || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const page = await api<{ items: Job[]; next: string | null }>(
        "/jobs?limit=200&before=" + encodeURIComponent(cursor),
      );
      if (page.next === cursor) {
        throw new Error(
          "The server repeated the same page. Retry after refreshing the run list.",
        );
      }
      if (alive.current) {
        setHistory((old) => ({
          items: mergeJobs(old.items, page.items),
          cursor: old.cursor === cursor ? page.next : old.cursor,
          initialized: true,
        }));
      }
    } catch (cause) {
      if (alive.current) setError(message(cause));
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  }
  return {
    items: mergeJobs(history.items, recent || []),
    cursor: history.initialized ? history.cursor : next,
    busy,
    error: error || statusError,
    loadOlder,
  };
}
