import { useEffect, useState } from "preact/hooks";
import { api, message } from "./platform.ts";
import type { Job } from "./platform.ts";

/** Preserve the last successful value on refresh/errors; never expose another URL's data. */
export function useResource<T>(
  path: string | null,
  interval = 10000,
  load?: (path: string) => Promise<T>,
) {
  const [snapshot, setSnapshot] = useState<
    {
      path: string | null;
      data: T | null;
      error: string;
      updated: number | null;
    }
  >({ path: null, data: null, error: "", updated: null });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!path) return;
    let stopped = false, timer: ReturnType<typeof setTimeout>;
    async function read() {
      // A hidden tab does not poll; the visibility listener resumes it.
      if (document.hidden) return;
      try {
        const value = await (load ? load(path!) : api<T>(path!));
        if (!stopped) {
          setSnapshot({ path, data: value, error: "", updated: Date.now() });
        }
      } catch (cause) {
        if (!stopped) {
          setSnapshot((old) => ({
            path,
            data: old.path === path ? old.data : null,
            updated: old.path === path ? old.updated : null,
            error: message(cause),
          }));
        }
      } finally {
        if (!stopped) timer = setTimeout(read, interval);
      }
    }
    const resume = () => {
      if (!stopped && !document.hidden) {
        clearTimeout(timer);
        read();
      }
    };
    document.addEventListener("visibilitychange", resume);
    read();
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [path, interval, revision, load]);
  return {
    data: snapshot.path === path ? snapshot.data : null,
    error: snapshot.path === path ? snapshot.error : "",
    updated: snapshot.path === path ? snapshot.updated : null,
    refresh: () => setRevision((value) => value + 1),
  };
}
export async function loadDeployments(path: string): Promise<Job[]> {
  const jobs: Job[] = [], seen = new Set<string>();
  let cursor: string | null = null;
  do {
    const page: { items: Job[]; next: string | null } = await api(
      path + (cursor ? "&before=" + encodeURIComponent(cursor) : ""),
    );
    jobs.push(...page.items);
    cursor = page.next;
    if (cursor && seen.has(cursor)) {
      throw new Error("Deployment pagination returned a repeated cursor.");
    }
    if (cursor) seen.add(cursor);
  } while (cursor);
  return jobs;
}
