export type Connection = {
  id: string;
  name: string;
  base_url: string;
  model: string;
  has_key: boolean;
  api_key_env?: string | null;
  context_length: number;
  max_tokens: number;
  tools: boolean;
  managed_job_id?: string;
  artifact_id?: string;
};
export type Suite = {
  id: string;
  tasks: number;
  total_tasks: number;
  splits: string[];
  suite_hash: string;
};
export type Artifact = {
  id: string;
  job_id: string;
  name: string;
  kind: string;
  status: string;
  size: number;
  files: { path: string; size: number; sha256: string }[];
  metadata: Record<string, unknown>;
};
export type Episode = {
  task: string;
  suite?: string;
  reward: number | null;
  passed: boolean;
  seconds?: number;
  error?: string;
  file?: string;
};
export type ChatOutput = {
  text: string;
  reasoning: string;
  tool_calls?: unknown[];
  seconds: number;
  usage?: Record<string, number>;
};
export type Job = {
  id: string;
  kind: string;
  name: string;
  status: string;
  created_at: number;
  started_at: number | null;
  updated_at: number;
  finished_at: number | null;
  heartbeat_at: number | null;
  worker_connected: boolean;
  cancel_requested: boolean;
  error: string | null;
  parent_id: string | null;
  attempt_number: number;
  config: {
    suite?: string;
    harness?: string;
    connection?: Connection;
    artifact_id?: string;
    protocol?: string;
    tasks?: string[];
    [key: string]: unknown;
  };
  result: {
    episodes?: Episode[];
    artifact_id?: string;
    connection_id?: string;
    mean_reward?: number | null;
    solve_rate?: number;
    outputs?: Record<string, ChatOutput>;
    [key: string]: unknown;
  } | null;
};
export type Event = {
  id: number;
  at: number;
  kind: string;
  payload: Record<string, unknown>;
};
export type Worker = {
  id: string;
  connected: boolean;
  sample_at: number;
  capabilities: string[];
  resources: {
    cpu_percent?: number;
    ram_used?: number;
    ram_total?: number;
    gpus: {
      index: number;
      name: string;
      memory_used: number;
      memory_total: number;
      utilization: number;
    }[];
  };
};
export type Conversation = {
  id: string;
  name: string;
  config: {
    connection_ids: string[];
    connections: Record<string, Connection>;
    [key: string]: unknown;
  };
  turns?: { id: string; prompt: string; job: Job }[];
};

export class ApiError extends Error {
  constructor(message: string, public status = 0) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const cookie = document.cookie.split(";").find((part) =>
    part.trim().startsWith("pg_csrf=")
  );
  if (cookie) {
    headers.set("X-CSRF-Token", decodeURIComponent(cookie.trim().slice(8)));
  }
  let storageKey = "";
  if (method === "POST") {
    const hash = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(path + JSON.stringify(body)),
    );
    storageKey = "pg-submit-" +
      Array.from(new Uint8Array(hash), (n) => n.toString(16).padStart(2, "0"))
        .join("");
    let key: string = crypto.randomUUID();
    try {
      key = sessionStorage.getItem(storageKey) || key;
      sessionStorage.setItem(storageKey, key);
    } catch { /* Storage is optional for transport. */ }
    headers.set("Idempotency-Key", key);
  }
  let response: Response;
  try {
    response = await fetch("/api/v1" + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(30000),
    });
  } catch {
    throw new ApiError(
      method === "POST"
        ? "Submission was not confirmed. Check Results before retrying; retrying this form reuses the same request key."
        : "The server could not be reached. Your jobs continue on the worker.",
    );
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/")) {
      location.assign("/login");
    }
    const fields = data?.error?.fields?.map((
      f: { field: string; message: string },
    ) => `${f.field}: ${f.message}`).join("; ");
    throw new ApiError(
      fields || data?.error?.message || `Request failed (${response.status})`,
      response.status,
    );
  }
  if (storageKey) {
    try {
      sessionStorage.removeItem(storageKey);
    } catch { /* Storage is optional. */ }
  }
  return data as T;
}

export const terminal = (job: Job) =>
  ["succeeded", "failed", "cancelled"].includes(job.status);
export const date = (value: number) =>
  new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(value * 1000);
export const number = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
export const metric = (value: unknown, precision = 2) =>
  number(value)?.toFixed(precision) ?? "—";
export const bytes = (value: unknown) =>
  number(value) === null ? "—" : `${(Number(value) / 1024 ** 3).toFixed(1)} GB`;
export const message = (cause: unknown) =>
  cause instanceof Error ? cause.message : "The operation failed";
export const field = (data: FormData, name: string) =>
  String(data.get(name) || "");
export const numeric = (data: FormData, name: string) =>
  Number(field(data, name));
