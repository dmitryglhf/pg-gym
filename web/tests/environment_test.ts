import { formatEnvironment, parseEnvironment } from "../lib/environment.ts";

Deno.test("environment preserves literal secrets and supports dotenv input", () => {
  const input =
    "# comment\nexport API_KEY=\" a=b\\nline \"\nURL=https://host/path#fragment\nOTHER='$HOME $(command)'\nEMPTY=";
  const values = parseEnvironment(input);
  if (
    values.API_KEY !== " a=b\nline " || values.OTHER !== "$HOME $(command)" ||
    values.URL !== "https://host/path#fragment" || values.EMPTY !== ""
  ) throw new Error("Changed literal values");
  if (
    JSON.stringify(values) !==
      JSON.stringify(parseEnvironment(formatEnvironment(values)))
  ) throw new Error("Round trip lost values");
});
Deno.test("environment rejects invalid and duplicate names without echoing secrets", () => {
  for (
    const input of ["KEY=secret\nKEY=other", "BAD NAME=secret", 'KEY="secret']
  ) {
    let failed = false;
    try {
      parseEnvironment(input);
    } catch (cause) {
      failed = true;
      if (String(cause).includes("secret")) {
        throw new Error("Error exposed a value");
      }
    }
    if (!failed) throw new Error("Invalid environment accepted");
  }
  if (parseEnvironment("__proto__=literal").__proto__ !== "literal") {
    throw new Error("Special name lost");
  }
});
