import { useEffect, useRef, useState } from "preact/hooks";
import { useResource } from "@/lib/query.ts";
import { api, message, terminal } from "@/lib/platform.ts";
import type { Job } from "@/lib/platform.ts";
import { openActivity } from "@/lib/workspace.ts";
import { Notice, Status } from "./PlatformUI.tsx";

export function OperationCard(
  { id, onComplete }: { id: string; onComplete?: (job: Job) => void },
) {
  const { data: job, error, refresh } = useResource<Job>(
    "/jobs/" + encodeURIComponent(id),
    3000,
  );
  const [actionError, setActionError] = useState("");
  const notified = useRef("");
  useEffect(() => {
    if (job && terminal(job) && notified.current !== job.id) {
      notified.current = job.id;
      onComplete?.(job);
    }
  }, [job, onComplete]);
  return (
    <section class="operation-card" aria-label="Submitted operation">
      <div>
        <strong>{job?.name || "Submission accepted"}</strong>
        <p class="muted">
          {job?.status === "queued"
            ? "Stored on the server; waiting for a capable worker. You can leave this screen."
            : job?.result?.connection_id && !terminal(job)
            ? "Server reported ready. It will remain active until stopped."
            : job
            ? `${job.kind.replaceAll("_", " ")} · ${job.status}`
            : id}
        </p>
      </div>
      <div class="inline-actions">
        {job?.result?.artifact_id &&
          ["model_import", "training"].includes(job.kind) && (
          <a
            class="button primary"
            href={`/models?artifact=${job.result.artifact_id}${
              typeof location !== "undefined" &&
                new URLSearchParams(location.search).get("return")
                ? "&return=" +
                  encodeURIComponent(
                    new URLSearchParams(location.search).get("return")!,
                  )
                : ""
            }`}
          >
            Open model & next steps
          </a>
        )}
        {job && <Status job={job} />}
        <button
          type="button"
          class="button secondary"
          onClick={() => openActivity(id)}
        >
          Open logs
        </button>
        <a href={`/jobs/${id}`}>Details</a>
        {job && !terminal(job) && (
          <button
            type="button"
            class="text-button"
            disabled={job.cancel_requested}
            onClick={async () => {
              if (
                confirm(
                  "Stop this operation? Completed partial results will remain available.",
                )
              ) {
                try {
                  setActionError("");
                  await api(`/jobs/${id}/cancel`, "POST");
                  refresh();
                } catch (cause) {
                  setActionError(message(cause));
                }
              }
            }}
          >
            {job.cancel_requested ? "Stop requested" : "Stop"}
          </button>
        )}
      </div>
      {(error || actionError || job?.error) && (
        <Notice error>{error || actionError || job?.error}</Notice>
      )}
    </section>
  );
}
