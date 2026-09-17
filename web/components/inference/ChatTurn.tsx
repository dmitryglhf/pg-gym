import { useEffect, useState } from "preact/hooks";
import { api, message, metric, terminal } from "@/lib/platform.ts";
import type { ChatOutput, Connection, Event, Job } from "@/lib/platform.ts";
import { openActivity } from "@/lib/workspace.ts";
import { Notice, Status } from "../PlatformUI.tsx";

/** Render by configured connection order, never by the arrival order of deltas. */
export function ChatTurn({ turn, ids, connections, onReuse }: {
  turn: { id: string; prompt: string; job: Job };
  ids: string[];
  connections: Record<string, Connection>;
  onReuse: (prompt: string) => void;
}) {
  const [job, setJob] = useState(turn.job),
    [outputs, setOutputs] = useState<Record<string, ChatOutput>>({});
  const [side, setSide] = useState(0);
  const [generating, setGenerating] = useState("");
  const [error, setError] = useState(""),
    [feedback, setFeedback] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    if (terminal(turn.job)) {
      setJob(turn.job);
      return;
    }
    let stopped = false, cursor = 0, timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const [current, batch] = await Promise.all([
          api<Job>(`/jobs/${turn.job.id}`),
          api<{ items: Event[]; next: number }>(
            `/jobs/${turn.job.id}/events?after=${cursor}`,
          ),
        ]);
        if (stopped) return;
        cursor = batch.next;
        setJob(current);
        setError("");
        for (const event of batch.items) {
          if (event.kind === "phase" && event.payload.phase === "generating") {
            setGenerating(String(event.payload.connection_id));
          }
        }
        setOutputs((old) => {
          const next = structuredClone(old);
          for (const event of batch.items) {
            if (event.kind !== "delta") continue;
            const value = next[String(event.payload.connection_id)] ||= {
              text: "",
              reasoning: "",
              seconds: 0,
            };
            value.text += String(event.payload.text || "");
            value.reasoning += String(event.payload.reasoning || "");
          }
          return next;
        });
        if (!terminal(current) || batch.items.length === 500) {
          timer = setTimeout(read, batch.items.length === 500 ? 50 : 1500);
        }
      } catch (cause) {
        if (!stopped) {
          setError(message(cause));
          timer = setTimeout(read, 5000);
        }
      }
    }
    read();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [turn.job.id]);
  const values = { ...outputs, ...job.result?.outputs };
  return (
    <article class="conversation-turn">
      <div class="prompt-bubble">
        <small>You · shared prompt</small>
        <p>{turn.prompt}</p>
      </div>
      {ids.length === 2 && (
        <div
          class="mobile-response-tabs"
          role="group"
          aria-label="Response model"
        >
          {[0, 1].map((index) => (
            <button
              key={index}
              type="button"
              class={`button ${side === index ? "primary" : "secondary"}`}
              aria-pressed={side === index}
              onClick={() => setSide(index)}
            >
              {index ? "B" : "A"} · {connections[ids[index]]?.name || "Model"}
            </button>
          ))}
        </div>
      )}
      <div class={`response-grid ${ids.length === 2 ? "split" : ""}`}>
        {ids.map((id, index) => {
          const output = values[id];
          return (
            <section
              class={`response-cell ${side === index ? "mobile-selected" : ""}`}
              key={id}
              aria-label={`Response ${index ? "B" : "A"}`}
            >
              <header>
                <strong>
                  {ids.length === 2 ? `${index ? "B" : "A"} · ` : ""}
                  {connections[id]?.name || id.slice(0, 12)}
                </strong>
                <small>{connections[id]?.model}</small>
              </header>
              {output?.reasoning && (
                <details>
                  <summary>Reasoning</summary>
                  <pre class="message-text">{output.reasoning}</pre>
                </details>
              )}
              <pre class="message-text">{output?.text || (terminal(job) ? "No text response saved." : index === 1 && !output && generating !== id ? "Waiting for model A, then model B…" : job.status === "queued" ? "Waiting for a worker…" : "Generating…")}</pre>
              {!!output?.tool_calls?.length && (
                <details>
                  <summary>Tool calls (not executed)</summary>
                  <pre class="json-view">{JSON.stringify(output.tool_calls, null, 2)}</pre>
                </details>
              )}
              {output && (
                <footer>
                  <small>
                    {output.seconds ? `${metric(output.seconds, 1)}s · ` : ""}
                    {output.usage?.completion_tokens ?? "—"} tokens
                  </small>
                  <button
                    type="button"
                    class="text-button"
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(output.text);
                        setFeedback(`Copied response ${index ? "B" : "A"}.`);
                      } catch {
                        setFeedback(
                          "Copy unavailable. Select the response text to copy it.",
                        );
                      }
                    }}
                  >
                    Copy
                  </button>
                </footer>
              )}
            </section>
          );
        })}
      </div>
      <div class="turn-actions">
        <Status job={job} />
        <button
          type="button"
          class="text-button"
          onClick={() => openActivity(job.id)}
        >
          Logs
        </button>
        <a href={`/jobs/${job.id}`}>Details</a>
        {!terminal(job)
          ? (
            <button
              type="button"
              class="text-button"
              disabled={busy || job.cancel_requested}
              onClick={async () => {
                setBusy(true);
                try {
                  setJob(await api<Job>(`/jobs/${job.id}/cancel`, "POST"));
                } catch (cause) {
                  setError(message(cause));
                } finally {
                  setBusy(false);
                }
              }}
            >
              {job.cancel_requested ? "Stopping…" : "Stop generation"}
            </button>
          )
          : (
            <button
              type="button"
              class="text-button"
              onClick={() => onReuse(turn.prompt)}
            >
              Reuse prompt
            </button>
          )}
      </div>
      {terminal(job) && job.status !== "succeeded" && (
        <Notice error>
          {job.error || "Generation stopped."}{" "}
          This entire turn is excluded from subsequent conversation context,
          including any saved partial response. Reuse the prompt to run it again
          for all selected models.
        </Notice>
      )}
      {error && <Notice error>{error}</Notice>}
      {feedback && <p role="status" class="muted">{feedback}</p>}
    </article>
  );
}
