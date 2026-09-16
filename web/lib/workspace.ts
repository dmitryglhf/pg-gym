import { useEffect, useRef, useState } from "preact/hooks";
import type { StateUpdater } from "preact/hooks";

export function readSession<T>(key: string, fallback: T): T {
  try {
    return JSON.parse(
      sessionStorage.getItem("pg-workspace:" + key) || "null",
    ) ?? fallback;
  } catch {
    return fallback;
  }
}
export function writeSession(key: string, value: unknown) {
  try {
    sessionStorage.setItem("pg-workspace:" + key, JSON.stringify(value));
  } catch { /* Optional persistence. */ }
}
/** Synchronous writes on edits also survive immediate full-page navigation. Never store secrets here. */
export function useDraft<T>(key: string, initial: T) {
  const defaults = useRef(initial);
  const [state, setState] = useState({ key, value: initial, restored: false });
  useEffect(() => {
    const stored = readSession(key, defaults.current);
    const value = stored && defaults.current && typeof stored === "object" &&
        !Array.isArray(stored)
      ? { ...defaults.current, ...stored }
      : stored;
    setState({ key, value, restored: true });
  }, [key]);
  const setValue = (update: StateUpdater<T>) =>
    setState((old) => {
      const previous = old.key === key ? old.value : defaults.current;
      const value = typeof update === "function"
        ? (update as (value: T) => T)(previous)
        : update;
      writeSession(key, value);
      return { key, value, restored: true };
    });
  return [
    state.key === key ? state.value : initial,
    setValue,
    state.key === key && state.restored,
  ] as const;
}
export function clearWorkspaceSession() {
  try {
    for (const key of Object.keys(sessionStorage)) {
      if (
        key.startsWith("pg-workspace:") || key.startsWith("pg-submit-") ||
        key === "pg-task-prompt"
      ) sessionStorage.removeItem(key);
    }
  } catch { /* Optional persistence. */ }
}
export function openActivity(jobId?: string) {
  globalThis.dispatchEvent(
    new CustomEvent("pg-open-activity", { detail: { jobId } }),
  );
}
export type ReturnTarget = "benchmark" | "training" | "inference";
export function preparationHref(target: ReturnTarget, artifact?: string) {
  return "/models?return=" + target +
    (artifact ? "&artifact=" + encodeURIComponent(artifact) : "");
}
export function returnHref(
  target: string | null,
  connection?: string,
  artifact?: string,
): string {
  const path = target === "benchmark"
    ? "/benchmark"
    : target === "training"
    ? "/rl"
    : "/inference";
  const query = new URLSearchParams();
  if (connection) query.set("connection", connection);
  if (artifact) query.set("artifact", artifact);
  return path + (query.size ? "?" + query : "");
}
