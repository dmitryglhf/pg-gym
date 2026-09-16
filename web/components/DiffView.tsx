export function DiffView(
  { diff, maxLines = 500 }: { diff: string; maxLines?: number },
) {
  const all = diff.split("\n");
  const lines = all.slice(0, maxLines);
  return (
    <div class="diff-frame">
      <pre
        class="diff-block"
        tabIndex={0}
        aria-label="Candidate source diff"
      ><code>{lines.map((line, i) => <span class={`diff-line ${diffClass(line)}`} key={i}>{line || " "}</span>)}</code></pre>
      {all.length > maxLines && (
        <div class="diff-truncated">
          Showing {maxLines} of {all.length}{" "}
          lines. Download the patch to inspect the complete diff.
        </div>
      )}
    </div>
  );
}

function diffClass(line: string): string {
  if (
    line.startsWith("diff --git") || line.startsWith("index ") ||
    line.startsWith("+++ ") || line.startsWith("--- ")
  ) return "diff-meta";
  if (line.startsWith("@@")) return "diff-hunk";
  if (line.startsWith("+")) return "diff-add";
  if (line.startsWith("-")) return "diff-remove";
  return "diff-context";
}
