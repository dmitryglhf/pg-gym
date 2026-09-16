import { useEffect, useRef, useState } from "preact/hooks";
import { LogStream } from "@/components/ConsolePanel.tsx";
import { Icon } from "@/components/Icon.tsx";
import { api, message } from "@/lib/platform.ts";
import type { Job } from "@/lib/platform.ts";
import { readSession, writeSession } from "@/lib/workspace.ts";

export default function ActivityDock() {
  const [open, setOpen] = useState(false),
    [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]),
    [cursor, setCursor] = useState<string | null>(null),
    [error, setError] = useState("");
  const closeButton = useRef<HTMLButtonElement>(null),
    trigger = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const query = new URLSearchParams(location.search);
    setSelected(query.get("job") || readSession("activity-job", ""));
    setOpen(
      query.get("panel") === "console" || readSession("activity-open", false),
    );
    function show(event: Event) {
      trigger.current = document.activeElement as HTMLElement;
      const id = (event as CustomEvent<{ jobId?: string }>).detail?.jobId;
      if (id) {
        setSelected(id);
        writeSession("activity-job", id);
      }
      setOpen(true);
      writeSession("activity-open", true);
    }
    globalThis.addEventListener("pg-open-activity", show);
    return () => globalThis.removeEventListener("pg-open-activity", show);
  }, []);
  function close() {
    setOpen(false);
    writeSession("activity-open", false);
    trigger.current?.focus();
  }
  useEffect(() => {
    if (!open) return;
    closeButton.current?.focus();
    function key(event: KeyboardEvent) {
      if (event.key === "Escape") close();
    }
    globalThis.addEventListener("keydown", key);
    return () => globalThis.removeEventListener("keydown", key);
  }, [open]);
  useEffect(() => {
    if (!open) return;
    let stopped = false;
    api<{ items: Job[]; next: string | null }>("/jobs").then((page) => {
      if (!stopped) {
        setJobs(page.items);
        setCursor(page.next);
        setError("");
      }
    }).catch((cause) => {
      if (!stopped) setError(message(cause));
    });
    return () => {
      stopped = true;
    };
  }, [open]);
  return (
    <div
      class={`activity-dock ${open ? "is-open" : ""} ${
        expanded ? "is-expanded" : ""
      }`}
    >
      {!open && (
        <button
          class="activity-launcher"
          type="button"
          onClick={(e) => {
            trigger.current = e.currentTarget;
            setOpen(true);
            writeSession("activity-open", true);
          }}
        >
          <Icon name="terminal" size={17} />Activity & logs
        </button>
      )}
      {open && (
        <section class="activity-drawer" aria-label="Activity and logs">
          <div class="dock-heading">
            <strong>
              <Icon name="terminal" size={18} />Activity{" "}
              <span class="muted">Read only</span>
            </strong>
            <div class="inline-actions">
              <button
                class="text-button"
                type="button"
                onClick={() => setExpanded(!expanded)}
              >
                {expanded ? "Reduce" : "Expand"}
              </button>
              <button
                ref={closeButton}
                class="icon-button"
                aria-label="Close activity panel"
                type="button"
                onClick={close}
              >
                <Icon name="close" />
              </button>
            </div>
          </div>
          <div class="dock-controls">
            <label>
              Run{" "}
              <select
                value={selected}
                onChange={(e) => {
                  setSelected(e.currentTarget.value);
                  writeSession("activity-job", e.currentTarget.value);
                }}
              >
                <option value="">Choose a run</option>
                {selected && !jobs.some((job) => job.id === selected) && (
                  <option value={selected}>{selected}</option>
                )}
                {jobs.map((job) => (
                  <option key={job.id} value={job.id}>
                    {job.name} · {job.status}
                  </option>
                ))}
              </select>
            </label>
            {cursor && (
              <button
                type="button"
                class="text-button"
                onClick={async () => {
                  try {
                    const page = await api<
                      { items: Job[]; next: string | null }
                    >("/jobs?before=" + encodeURIComponent(cursor));
                    setJobs((
                      old,
                    ) => [
                      ...old,
                      ...page.items.filter((item) =>
                        !old.some((j) => j.id === item.id)
                      ),
                    ]);
                    setCursor(page.next);
                  } catch (cause) {
                    setError(message(cause));
                  }
                }}
              >
                Older runs
              </button>
            )}
          </div>
          {error && <p role="alert" class="notice error">{error}</p>}
          {selected
            ? <LogStream key={selected} id={selected} />
            : (
              <p class="empty-state">
                Choose a run, or use “Open logs” beside an operation. New
                submissions never replace the run you are reading.
              </p>
            )}
        </section>
      )}
    </div>
  );
}
