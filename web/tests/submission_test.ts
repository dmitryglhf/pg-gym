/// <reference lib="dom" />
import { api, ApiError } from "../lib/platform.ts";

function assert(value: unknown, message: string) {
  if (!value) throw new Error(message);
}
Deno.test("an unconfirmed submission keeps its key until a valid acknowledgement", async () => {
  const originalFetch = globalThis.fetch;
  const documentDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    "document",
  );
  const keys: (string | null)[] = [];
  const replies = ["{", "null", '{"id":"accepted"}', '{"id":"new-run"}'];
  Object.defineProperty(globalThis, "document", {
    value: { cookie: "" },
    configurable: true,
  });
  globalThis.fetch = (_input, init) => {
    keys.push(new Headers(init?.headers).get("Idempotency-Key"));
    return Promise.resolve(
      new Response(replies.shift(), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );
  };
  try {
    const body = { name: "retry scenario", tasks: ["a"] };
    for (let i = 0; i < 2; i++) {
      let failed = false;
      try {
        await api("/benchmarks", "POST", body);
      } catch (cause) {
        failed = cause instanceof ApiError && cause.status === 0;
      }
      assert(failed, "Invalid acknowledgement must report an unknown outcome");
    }
    await api("/benchmarks", "POST", body);
    await api("/benchmarks", "POST", body);
    assert(
      keys[0] && keys[0] === keys[1] && keys[1] === keys[2],
      "Retries must preserve the key",
    );
    assert(keys[2] !== keys[3], "A new confirmed run needs a fresh key");
  } finally {
    globalThis.fetch = originalFetch;
    if (documentDescriptor) {
      Object.defineProperty(globalThis, "document", documentDescriptor);
    } else Reflect.deleteProperty(globalThis, "document");
  }
});
