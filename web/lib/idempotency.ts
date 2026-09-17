import { sha256 } from "@noble/hashes/sha2.js";

// A platform served over LAN HTTP has getRandomValues, but no subtle/randomUUID.
const pending = new Map<string, string>();
export function requestIdentity(path: string, body: unknown): string {
  return "pg-submit-" +
    Array.from(
      sha256(new TextEncoder().encode(path + JSON.stringify(body))),
      (value) => value.toString(16).padStart(2, "0"),
    ).join("");
}
export function requestKey(identity: string): string {
  let key = pending.get(identity);
  try {
    key = sessionStorage.getItem(identity) || key;
  } catch { /* Fall back to this tab's memory. */ }
  if (!key) {
    key = Array.from(
      crypto.getRandomValues(new Uint8Array(16)),
      (value) => value.toString(16).padStart(2, "0"),
    ).join("");
  }
  pending.set(identity, key);
  try {
    sessionStorage.setItem(identity, key);
  } catch { /* A retry still reuses the in-memory key. */ }
  return key;
}
export function forgetRequest(identity: string) {
  pending.delete(identity);
  try {
    sessionStorage.removeItem(identity);
  } catch { /* Optional persistence. */ }
}
export function isSubmission(path: string) {
  return /^\/(benchmarks|models\/imports|deployments|training-runs|evaluations|conversations\/[^/]+\/turns|jobs\/[^/]+\/retries)$/
    .test(path);
}
