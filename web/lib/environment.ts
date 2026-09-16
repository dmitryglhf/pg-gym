export function parseEnvironment(text: string): Record<string, string> {
  const variables: Record<string, string> = Object.create(null);
  for (const [index, source] of text.split(/\r?\n/).entries()) {
    const line = source.trim();
    if (!line || line.startsWith("#")) continue;
    const match = /^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/.exec(
      line,
    );
    if (!match) throw new Error(`Line ${index + 1}: expected KEY=VALUE.`);
    const [, name, raw] = match;
    if (Object.hasOwn(variables, name)) {
      throw new Error(`Line ${index + 1}: duplicate variable ${name}.`);
    }
    let value = raw;
    if (raw.startsWith('"')) {
      try {
        value = JSON.parse(raw);
        if (typeof value !== "string") throw new Error();
      } catch {
        throw new Error(
          `Line ${
            index + 1
          }: use a complete double-quoted string; escape newlines as \\n.`,
        );
      }
    } else if (raw.startsWith("'")) {
      if (!raw.endsWith("'") || raw.length < 2) {
        throw new Error(`Line ${index + 1}: missing closing quote.`);
      }
      value = raw.slice(1, -1);
    }
    variables[name] = value;
  }
  return variables;
}
export function formatEnvironment(variables: Record<string, string>): string {
  return Object.entries(variables).map(([name, value]) =>
    `${name}=${JSON.stringify(value)}`
  ).join("\n");
}
