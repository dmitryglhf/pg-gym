import { createRequire } from "node:module";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { mkdir, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";
const require = createRequire(import.meta.url);
const resolve = (name) =>
  require.resolve(name, {
    paths: [
      dirname(fileURLToPath(import.meta.url)),
      ...(process.env.UI_TEST_MODULES || "").split(":"),
      ...(process.env.UI_PLAYWRIGHT_MODULES || "").split(":"),
    ].filter(Boolean),
  });
const { build } = require(resolve("esbuild"));
const { chromium } = require(resolve("playwright"));
const web = fileURLToPath(new URL("../../", import.meta.url));
const output = process.env.UI_REVIEW_OUTPUT || join(web, "../review-output");
await mkdir(output, { recursive: true });
const bundle = await build({
  entryPoints: [join(web, "tests/browser/entry.tsx")],
  bundle: true,
  write: false,
  outfile: "bundle.js",
  format: "esm",
  jsx: "automatic",
  jsxImportSource: "preact",
  alias: {
    "@": web,
    "preact": dirname(resolve("preact/package.json")),
    "@noble/hashes": dirname(resolve("@noble/hashes/sha2.js")),
  },
  logLevel: "silent",
});
const js = bundle.outputFiles.find((f) => f.path.endsWith(".js")).contents,
  css = bundle.outputFiles.find((f) => f.path.endsWith(".css")).contents;
const server = createServer((req, res) => {
  const pathname = new URL(req.url, "http://local").pathname;
  if (pathname.startsWith("/api/")) {
    res.writeHead(500);
    res.end("Missing mock");
    return;
  }
  res.setHeader(
    "content-type",
    pathname === "/bundle.js"
      ? "text/javascript"
      : pathname === "/bundle.css"
      ? "text/css"
      : "text/html",
  );
  res.end(
    pathname === "/bundle.js"
      ? js
      : pathname === "/bundle.css"
      ? css
      : '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/bundle.css"></head><body><div id="app"></div><script type="module" src="/bundle.js"></script></body></html>',
  );
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox", "--no-zygote", "--disable-gpu"],
  ...(process.env.UI_CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.UI_CHROMIUM_EXECUTABLE }
    : {}),
});
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
const connection = (id, name) => ({
  id,
  name,
  base_url: "https://provider.example/v1",
  model: "example/model",
  has_key: true,
  api_key_env: null,
  tools: true,
  context_length: 32768,
  max_tokens: 4096,
});
const job = (id, name, status = "succeeded", kind = "benchmark") => ({
  id,
  name,
  kind,
  status,
  created_at: 100 + Number(id.replace(/\D/g, "")),
  started_at: 100,
  updated_at: 110,
  finished_at: status === "succeeded" ? 110 : null,
  heartbeat_at: 110,
  worker_id: "gpu",
  worker_connected: true,
  cancel_requested: false,
  error: null,
  parent_id: null,
  attempt_number: 1,
  config: {
    suite: "postgres",
    tasks: ["task-a"],
    task_hashes: { "task-a": "hash-a" },
    protocol: "agentic-benchmark.v1",
    connection_id: "a",
    connection: connection("a", "Model A"),
  },
  result: { mean_reward: 0.7, execution_errors: 0, episodes: [] },
});
async function fixture(path = "/", width = 1440) {
  const context = await browser.newContext({
      viewport: { width, height: 1000 },
    }),
    page = await context.newPage(),
    errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const state = {
    connections: [connection("a", "Model A"), connection("b", "Model B")],
    jobs: [job("3", "Recent three"), job("2", "Recent two")],
    older: [job("1", "Older one")],
    deployments: [],
    artifacts: [{
      id: "base",
      job_id: "download",
      name: "Example base model",
      kind: "model",
      status: "ready",
      size: 1024,
      files: [],
      metadata: { repository: "example/model" },
    }],
    workers: [{
      id: "gpu",
      connected: true,
      sample_at: Date.now() / 1000,
      capabilities: [
        "chat",
        "benchmark",
        "model_import",
        "deployment",
        "training",
        "evaluation",
      ],
      resources: {
        cpu_percent: 3,
        ram_used: 1e9,
        ram_total: 16e9,
        gpus: [{
          index: 0,
          name: "Single GPU",
          memory_used: 1e9,
          memory_total: 24e9,
          utilization: 0,
        }],
      },
    }],
    conversations: [],
    events: {},
    environment: { revision: 1, variables: {} },
    requests: [],
    turnDelay: 0,
    failures: {},
    postCount: 0,
  };
  const reply = (route, data, status = 200) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url()),
      path = url.pathname.slice(7),
      method = request.method(),
      body = request.postDataJSON();
    state.requests.push({
      path,
      method,
      body,
      key: request.headers()["idempotency-key"],
    });
    if (state.failures[path]) {
      const fail = state.failures[path];
      if (fail.once) delete state.failures[path];
      if (fail.abort) return route.abort();
      return route.fulfill({
        status: fail.status || 200,
        contentType: "application/json",
        body: fail.body || "{",
      });
    }
    if (path === "/me") {
      return reply(route, { id: "user-1", username: "reviewer" });
    }
    if (path === "/auth/options") {
      return reply(route, { registration_code_required: false });
    }
    if (path === "/auth/register") {
      return reply(route, { id: "registered", username: "reviewer" }, 201);
    }
    if (path === "/auth/login") {
      return reply(route, { id: "user-1", username: "reviewer" });
    }
    if (path === "/connections" && method === "GET") {
      return reply(route, state.connections);
    }
    if (path === "/connections" && method === "POST") {
      const value = { id: "c", ...body };
      state.connections.push(value);
      return reply(route, value, 201);
    }
    if (path.startsWith("/connections/") && method === "PUT") {
      const id = path.split("/")[2],
        i = state.connections.findIndex((c) => c.id === id);
      state.connections[i] = {
        ...state.connections[i],
        ...body,
        has_key: body.api_key_env
          ? true
          : body.api_key === ""
          ? false
          : state.connections[i].has_key,
      };
      return reply(route, state.connections[i]);
    }
    if (path.endsWith("/check")) {
      return reply(route, { ok: true, message: "Model is available" });
    }
    if (path === "/environment" && method === "GET") {
      return reply(route, {
        revision: state.environment.revision,
        names: Object.keys(state.environment.variables),
      });
    }
    if (path === "/environment" && method === "PUT") {
      state.environment = {
        revision: state.environment.revision + 1,
        variables: Object.fromEntries(
          Object.entries(body.variables).map((
            [k, v],
          ) => [k, v ?? state.environment.variables[k]]),
        ),
      };
      return reply(route, {
        revision: state.environment.revision,
        names: Object.keys(state.environment.variables),
      });
    }
    if (path === "/environment/reveal") return reply(route, state.environment);
    if (path === "/suites") {
      return reply(route, [{
        id: "postgres",
        tasks: 2,
        total_tasks: 2,
        splits: ["train", "test"],
        suite_hash: "suite",
      }]);
    }
    if (path === "/suites/postgres/tasks") {
      return reply(route, [{ name: "task-a" }, { name: "task-b" }]);
    }
    if (path.startsWith("/suites/postgres/tasks/")) {
      return reply(route, {
        name: path.split("/").at(-1),
        prompt: "Explain and improve this PostgreSQL query.",
        task_hash: "hash-a",
      });
    }
    if (path === "/harness-profiles" || path === "/api-tokens") {
      return reply(route, []);
    }
    if (path === "/artifacts") {
      return reply(route, state.artifacts);
    }
    if (path === "/capabilities") {
      return reply(route, { workers: state.workers });
    }

    if (path === "/jobs") {
      return reply(
        route,
        url.searchParams.get("kind") === "deployment"
          ? { items: state.deployments, next: null }
          : url.searchParams.has("before")
          ? { items: state.older, next: null }
          : { items: state.jobs, next: state.older.length ? "older" : null },
      );
    }
    if (/^\/jobs\/[^/]+\/events$/.test(path)) {
      const events = (state.events[path.split("/")[2]] || []).filter((e) =>
        e.id > Number(url.searchParams.get("after") || 0)
      );
      return reply(route, {
        items: events,
        next: events.at(-1)?.id || Number(url.searchParams.get("after") || 0),
      });
    }
    if (/^\/jobs\/[^/]+$/.test(path)) {
      return reply(
        route,
        [
          ...state.jobs,
          ...state.older,
          ...state.deployments,
          ...state.conversations.flatMap((c) =>
            c.turns?.map((t) => t.job) || []
          ),
        ].find((j) => j.id === path.split("/")[2]) ||
          job(path.split("/")[2], "Operation"),
      );
    }
    if (
      [
        "/benchmarks",
        "/training-runs",
        "/evaluations",
        "/models/imports",
        "/deployments",
      ].includes(path)
    ) {
      const j = {
        ...job(
          "new-" + (++state.postCount),
          body.name || "New run",
          "queued",
          path === "/benchmarks"
            ? "benchmark"
            : path === "/training-runs"
            ? "training"
            : path === "/evaluations"
            ? "evaluation"
            : path === "/deployments"
            ? "deployment"
            : "model_import",
        ),
        config: body,
        result: null,
      };
      state.jobs.unshift(j);
      if (path === "/deployments") state.deployments.unshift(j);
      return reply(route, j, 202);
    }
    if (path === "/conversations" && method === "GET") {
      return reply(route, state.conversations);
    }
    if (path === "/conversations" && method === "POST") {
      const c = {
        id: "chat-" + (state.conversations.length + 1),
        name: body.name,
        config: {
          ...body,
          connections: Object.fromEntries(
            state.connections.map((c) => [c.id, c]),
          ),
        },
        turns: [],
      };
      state.conversations.unshift(c);
      return reply(route, c, 201);
    }
    if (/^\/conversations\/[^/]+$/.test(path)) {
      return reply(
        route,
        state.conversations.find((c) => c.id === path.split("/")[2]),
        state.conversations.some((c) => c.id === path.split("/")[2])
          ? 200
          : 404,
      );
    }
    if (path.endsWith("/turns")) {
      await pause(state.turnDelay);
      const c = state.conversations.find((c) => c.id === path.split("/")[2]),
        j = {
          ...job(
            "chat-job-" + (++state.postCount),
            "Chat response",
            "queued",
            "chat",
          ),
          result: null,
        };
      c.turns.push({
        id: "turn-" + state.postCount,
        prompt: body.prompt,
        job: j,
      });
      return reply(route, j, 202);
    }
    if (path.endsWith("/cancel") || path.endsWith("/stop")) {
      const id = path.split("/")[2],
        j = state.jobs.find((j) => j.id === id) ||
          state.deployments.find((j) => j.id === id);
      if (j) {
        j.cancel_requested = true;
        j.status = "cancelling";
      }
      return reply(route, j);
    }
    return reply(
      route,
      { error: { message: `Unmocked ${method} ${path}` } },
      404,
    );
  });
  await page.goto(origin + path);
  await page.locator("main .loading-state").first().waitFor({
    state: "hidden",
    timeout: 10000,
  }).catch(() => {});
  await pause(250);
  return { page, state, errors, context };
}
const results = [];
async function test(name, fn) {
  if (
    process.env.UI_REVIEW_CASE &&
    !new RegExp(process.env.UI_REVIEW_CASE, "i").test(name)
  ) return;
  let f;
  try {
    f = await fixture(...(fn.fixture || []));
    await fn(f);
    assert.deepEqual(f.errors, []);
    results.push({ name, status: "passed" });
    console.log("PASS", name);
  } catch (e) {
    results.push({ name, status: "failed", error: String(e) });
    console.log("FAIL", name, String(e));
    if (f) {
      await f.page.screenshot({
        path: join(output, `failure-${results.length}.png`),
        fullPage: true,
      });
    }
  } finally {
    await f?.context.close();
  }
}
function at(path, fn, width) {
  fn.fixture = [path, width || 1440];
  return fn;
}
await test(
  "Floating monochrome navigation has one Home link and original shadows",
  at("/", async ({ page }) => {
    assert.equal(await page.locator(".tool-rail a[href='/']").count(), 1);
    assert.equal(await page.locator(".product-brand,.nav-collapse").count(), 0);
    const style = await page.locator(".tool-rail").evaluate((e) => {
      const s = getComputedStyle(e), b = e.getBoundingClientRect();
      return {
        left: b.left,
        top: b.top,
        width: b.width,
        shadow: s.boxShadow,
        radius: s.borderRadius,
      };
    });
    assert.equal(style.left, 16);
    assert.equal(style.width, 100);
    assert.notEqual(style.shadow, "none");
    assert.equal(style.radius, "28px");
    const labels = await page.locator(".tool-nav a").evaluateAll((links) =>
      links.map((link) => {
        const label = link.querySelector(":scope > span:last-child");
        const range = document.createRange();
        range.selectNodeContents(label);
        const box = link.getBoundingClientRect();
        return {
          name: label.textContent,
          centered: getComputedStyle(label).textAlign === "center",
          contained: [...range.getClientRects()].every((line) =>
            line.left >= box.left && line.right <= box.right
          ),
        };
      })
    );
    assert.ok(
      labels.every((label) => label.centered && label.contained),
      JSON.stringify(labels),
    );
    await page.screenshot({
      path: join(output, "workspace-desktop.png"),
      fullPage: true,
    });
  }),
);
await test(
  "Benchmark model selection survives reload after arriving from preparation",
  at("/benchmark?connection=a", async ({ page }) => {
    await page.getByLabel("Model connection").selectOption("b");
    await page.reload();
    await page.waitForFunction(() =>
      document.querySelector("select")?.value === "b"
    );
    assert.equal(await page.getByLabel("Model connection").inputValue(), "b");
  }),
);
await test(
  "Cancel inline key editor does not lock reopened connection form; public access clears key",
  at("/models?connection=a", async ({ page, state }) => {
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByRole("button", { name: "+ Add key here", exact: true })
      .click();
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    assert.equal(
      await page.getByRole("button", { name: "Save connection", exact: true })
        .isEnabled(),
      true,
    );
    await page.getByLabel("API key", { exact: true }).selectOption("");
    await page.getByRole("button", { name: "Save connection", exact: true })
      .click();
    await page.waitForTimeout(300);
    assert.equal(
      state.requests.findLast((r) =>
        r.method === "PUT" && r.path === "/connections/a"
      ).body.api_key,
      "",
    );
  }),
);
await test(
  "Chat send disables edits until acknowledgement and keeps a stable turn",
  at("/inference?connection=a", async ({ page, state }) => {
    state.turnDelay = 700;
    await page.getByLabel("Message for the model").fill("First prompt");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.waitForTimeout(150);
    assert.equal(await page.locator("#chat-prompt").isDisabled(), true);
    await page.waitForTimeout(900);
    assert.equal(await page.locator("#chat-prompt").inputValue(), "");
    assert.equal(await page.locator(".conversation-turn").count(), 1);
  }),
);
await test(
  "Mobile A/B layout and floating navigation fit the viewport",
  at("/inference?connection=a", async ({ page }) => {
    await page.getByLabel("Model B · optional").selectOption("b");
    await page.locator("#chat-prompt").fill("Compare");
    await page.getByRole("button", { name: "Send to both" }).click();
    await page.waitForTimeout(450);
    assert.equal(await page.locator(".response-cell:visible").count(), 1);
    await page.getByRole("button", { name: "B · Model B", exact: true })
      .click();
    assert.equal(
      await page.locator(".response-cell.mobile-selected").getAttribute(
        "aria-label",
      ),
      "Response B",
    );
    assert.equal(
      await page.evaluate(() =>
        document.documentElement.scrollWidth <= innerWidth
      ),
      true,
    );
    await page.screenshot({
      path: join(output, "inference-mobile.png"),
      fullPage: true,
    });
  }, 390),
);
await test(
  "History retains loaded runs when new jobs shift the recent page",
  at("/results", async ({ page, state }) => {
    await page.getByRole("button", { name: "Load older jobs" }).click();
    await page.getByRole("link", { name: "Older one", exact: true }).waitFor();
    state.jobs = [job("4", "New four"), state.jobs[0]];
    await page.getByRole("link", { name: "New four", exact: true }).waitFor({
      timeout: 8000,
    });
    assert.equal(
      await page.getByRole("link", { name: "Recent two", exact: true }).count(),
      1,
    );
  }),
);
await test(
  "HTTP-compatible submit does not require secure-context crypto APIs",
  at("/benchmark?connection=a", async ({ page, state }) => {
    await page.evaluate(() => {
      Object.defineProperty(crypto, "subtle", {
        value: undefined,
        configurable: true,
      });
      Object.defineProperty(crypto, "randomUUID", {
        value: undefined,
        configurable: true,
      });
    });
    await page.getByLabel("Task", { exact: true }).selectOption("task-a");
    await page.getByRole("button", { name: "Run benchmark", exact: true })
      .click();
    await page.waitForTimeout(300);
    const req = state.requests.find((r) =>
      r.method === "POST" && r.path === "/benchmarks"
    );
    assert.ok(req?.key);
    assert.ok(/^[\w-]+$/.test(req.key));
  }),
);

await test(
  "Model preparation and server settings survive navigation",
  at("/models?add", async ({ page }) => {
    await page.getByLabel("Hugging Face repository").fill(
      "team/preserved-model",
    );
    await page.getByRole("button", { name: "Existing API", exact: true })
      .click();
    await page.getByLabel("Display name", { exact: true }).fill("My endpoint");
    await page.getByRole("button", { name: "Hugging Face", exact: true })
      .click();
    assert.equal(
      await page.getByLabel("Hugging Face repository").inputValue(),
      "team/preserved-model",
    );
    await page.getByRole("button", { name: "Add model", exact: true }).click();
    await page.getByLabel("What will you use this server for?").selectOption(
      "harness",
    );
    await page.getByLabel("Tool parser").selectOption("hermes");
    await page.getByText("Server settings", { exact: true }).click();
    await page.getByLabel("Context window").fill("8192");
    await page.getByRole("button", { name: /Model A External endpoint/ })
      .click();
    await page.getByRole("button", { name: /Example base model Downloaded/ })
      .click();
    assert.equal(await page.getByLabel("Tool parser").inputValue(), "hermes");
    await page.reload();
    await page.getByText("Server settings", { exact: true }).click();
    assert.equal(await page.getByLabel("Context window").inputValue(), "8192");
  }),
);
await test(
  "Closing account variables keeps unsaved secrets in memory only",
  at("/models", async ({ page }) => {
    await page.getByRole("button", { name: "Keys & variables", exact: true })
      .click();
    await page.getByRole("button", { name: "Add variable", exact: true })
      .click();
    await page.getByLabel("Variable 1", { exact: true }).fill("REVIEW_KEY");
    await page.getByLabel("Value 1", { exact: true }).fill(
      "temporary-secret-value",
    );
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await page.getByRole("button", { name: "Keys & variables", exact: true })
      .click();
    assert.equal(
      await page.getByLabel("Value 1", { exact: true }).inputValue(),
      "temporary-secret-value",
    );
    assert.equal(
      await page.evaluate(() =>
        JSON.stringify(sessionStorage).includes("temporary-secret-value")
      ),
      false,
    );
  }),
);
await test(
  "Invalid advanced input is revealed by form validation",
  at("/models?add", async ({ page }) => {
    await page.getByRole("button", { name: "Existing API", exact: true })
      .click();
    await page.getByLabel("Display name", { exact: true }).fill("Endpoint");
    await page.getByLabel("API base URL").fill("https://example.com/v1");
    await page.getByLabel("Model identifier").fill("model");
    await page.getByText("Advanced settings", { exact: true }).click();
    await page.getByLabel("Context length").fill("5");
    await page.getByText("Advanced settings", { exact: true }).click();
    await page.getByRole("button", { name: "Save connection", exact: true })
      .click();
    assert.equal(await page.getByLabel("Context length").isVisible(), true);
  }),
);
await test(
  "Malformed submit acknowledgement retains the same idempotency key",
  at("/benchmark?connection=a", async ({ page, state }) => {
    await page.getByLabel("Task", { exact: true }).selectOption("task-a");
    state.failures["/benchmarks"] = { once: true, body: "{" };
    await page.getByRole("button", { name: "Run benchmark", exact: true })
      .click();
    await page.getByRole("alert").filter({ hasText: "incomplete" }).waitFor();
    await page.getByRole("button", { name: "Run benchmark", exact: true })
      .click();
    await page.waitForFunction(() =>
      !document.querySelector("form[aria-busy='true']")
    );
    const requests = state.requests.filter((r) =>
      r.method === "POST" && r.path === "/benchmarks"
    );
    assert.equal(requests.length, 2);
    assert.equal(requests[0].key, requests[1].key);
  }),
);
await test(
  "Streaming deltas do not duplicate when a queued chat starts running",
  at("/inference?connection=a", async ({ page, state }) => {
    await page.locator("#chat-prompt").fill("Stream please");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.locator(".conversation-turn").waitFor();
    const j = state.conversations[0].turns[0].job;
    j.status = "preparing";
    state.events[j.id] = [{
      id: 1,
      kind: "delta",
      payload: { connection_id: "a", text: "Unique fragment" },
    }];
    await page.getByText("Unique fragment", { exact: true }).waitFor();
    j.status = "running";
    await page.waitForTimeout(4300);
    assert.equal(
      await page.locator(".message-text").first().textContent(),
      "Unique fragment",
    );
  }),
);
await test(
  "Open console updates runs without changing the selected run",
  at("/", async ({ page, state }) => {
    await page.getByRole("button", { name: "Activity & logs", exact: true })
      .click();
    await page.getByLabel("Run", { exact: true }).selectOption("3");
    state.jobs.unshift(job("4", "Just submitted"));
    await page.getByRole("option", { name: /Just submitted/ }).waitFor({
      state: "attached",
      timeout: 8000,
    });
    assert.equal(
      await page.getByLabel("Run", { exact: true }).inputValue(),
      "3",
    );
    await page.getByRole("button", { name: "Close activity panel" }).click();
    assert.equal(
      await page.getByRole("button", { name: "Activity & logs", exact: true })
        .evaluate((e) => e === document.activeElement),
      true,
    );
  }),
);
await test(
  "Missing model deep link cannot silently select another model",
  at("/models?artifact=removed", async ({ page }) => {
    await page.getByText(/The selected model is not in the current list/)
      .waitFor();
    assert.equal(
      await page.getByRole("button", { name: "Start server", exact: true })
        .count(),
      0,
    );
  }),
);
await test(
  "Login returns to the same work and malformed return URLs remain usable",
  at("/login?next=http%3A%2F%2F%5B", async ({ page }) => {
    await page.getByLabel("Username", { exact: true }).fill("reviewer");
    await page.getByLabel("Password", { exact: true }).fill("review-password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.waitForURL(origin + "/");
  }),
);
for (
  const [path, name] of [
    ["/models", "models"],
    ["/benchmark?connection=a", "benchmark"],
    ["/rl?artifact=base", "training"],
    ["/results", "history"],
  ]
) {
  await test(
    `${name} fits a narrow viewport`,
    at(path, async ({ page }) => {
      assert.equal(
        await page.evaluate(() =>
          document.documentElement.scrollWidth <= innerWidth
        ),
        true,
      );
      await page.screenshot({
        path: join(output, `${name}-mobile.png`),
        fullPage: true,
      });
    }, 390),
  );
}

await test(
  "Busy GPU requires explicit queuing and keeps a stop action visible",
  at("/rl?artifact=base", async ({ page, state }) => {
    const server = {
      ...job("server1", "Existing model server", "running", "deployment"),
      config: { artifact_id: "base" },
      result: { connection_id: "local" },
    };
    state.deployments = [server];
    await page.reload();
    await page.getByRole("button", { name: "Stop server to free GPU" })
      .waitFor();
    assert.equal(
      await page.getByRole("button", { name: "Start training", exact: true })
        .isDisabled(),
      true,
    );
    await page.getByLabel("Queue until the GPU is released").check();
    await page.getByRole("button", { name: "Queue training", exact: true })
      .click();
    await page.locator(".operation-card").waitFor();
    assert.equal(
      state.requests.filter((r) =>
        r.path === "/training-runs" && r.method === "POST"
      ).length,
      1,
    );
    assert.equal(
      state.requests.filter((r) =>
        r.path.endsWith("/stop") && r.method === "POST"
      ).length,
      0,
    );
  }),
);
await test(
  "Cloned task sets containing removed tasks cannot submit a partial benchmark",
  at("/benchmark", async ({ page, state }) => {
    state.jobs[0].config.tasks = ["task-a", "removed-task"];
    await page.goto(origin + "/benchmark?clone=3");
    await page.getByText(/Copied the saved task set and limits/).waitFor();
    assert.equal(
      await page.getByRole("button", { name: "Run benchmark", exact: true })
        .isDisabled(),
      true,
    );
  }),
);
await test(
  "A successful registration followed by a login outage remains in sign-in mode",
  at("/login", async ({ page, state }) => {
    await page.getByRole("button", { name: "Create an account", exact: true })
      .click();
    await page.getByLabel("Username", { exact: true }).fill("reviewer");
    await page.getByLabel("Password", { exact: true }).fill("review-password");
    state.failures["/auth/login"] = {
      once: true,
      status: 503,
      body: JSON.stringify({ error: { message: "Temporary outage" } }),
    };
    await page.getByRole("button", { name: "Create account", exact: true })
      .click();
    await page.getByRole("heading", { name: "Sign in", exact: true }).waitFor();
    await page.getByRole("alert").filter({ hasText: "Temporary outage" })
      .waitFor();
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.waitForURL(origin + "/");
    assert.equal(
      state.requests.filter((r) => r.path === "/auth/register").length,
      1,
    );
  }),
);
await test(
  "Full screen uses two stable columns and Escape restores navigation",
  at("/inference?connection=a", async ({ page, state }) => {
    await page.getByLabel("Model B · optional").selectOption("b");
    await page.locator("#chat-prompt").fill("Explain");
    await page.getByRole("button", { name: "Send to both" }).click();
    await page.locator(".conversation-turn").waitFor();
    const j = state.conversations[0].turns[0].job;
    j.status = "running";
    state.events[j.id] = [{
      id: 1,
      kind: "delta",
      payload: { connection_id: "a", text: "Answer A" },
    }, {
      id: 2,
      kind: "phase",
      payload: { phase: "generating", connection_id: "b" },
    }];
    await page.getByText("Answer A", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Full screen", exact: true })
      .click();
    await page.locator(".tool-rail").waitFor({ state: "hidden" });
    assert.equal(await page.locator(".tool-rail").isVisible(), false);
    assert.equal(await page.locator(".response-cell:visible").count(), 2);
    await page.getByRole("region", { name: "Response B" }).getByText(
      "Generating…",
      { exact: true },
    ).waitFor();
    await page.screenshot({
      path: join(output, "inference-desktop-fullscreen.png"),
      fullPage: true,
    });
    await page.keyboard.press("Escape");
    await page.locator(".tool-rail").waitFor({ state: "visible" });
    assert.equal(await page.locator(".tool-rail").isVisible(), true);
  }),
);

await test(
  "Older active runs keep updating after leaving the first page",
  at("/results", async ({ page, state }) => {
    state.jobs[0].status = "running";
    state.jobs[0].finished_at = null;
    await page.reload();
    await page.getByRole("button", { name: "Load older jobs" }).click();
    await page.getByRole("link", { name: "Older one", exact: true }).waitFor();
    const old = { ...state.jobs[0], status: "succeeded", updated_at: 120 };
    state.older.push(old);
    state.jobs = [job("4", "New four"), state.jobs[1]];
    await page.getByRole("row").filter({
      has: page.getByRole("link", { name: "Recent three", exact: true }),
    }).getByText("succeeded", { exact: true }).waitFor({ timeout: 10000 });
    assert.ok(state.requests.some((r) => r.path === "/jobs/3"));
  }),
);

await test(
  "A suspended history can fill a gap larger than the recent page",
  at("/results", async ({ page, state }) => {
    await page.getByRole("button", { name: "Load older jobs" }).click();
    await page.getByRole("link", { name: "Older one", exact: true }).waitFor();
    state.older = [
      job("5", "Missed five"),
      job("4", "Missed four"),
      ...state.jobs,
      ...state.older,
    ];
    state.jobs = [job("6", "Latest six")];
    await page.getByRole("link", { name: "Latest six", exact: true }).waitFor({
      timeout: 8000,
    });
    await page.getByRole("button", { name: "Load older jobs" }).click();
    await page.getByRole("link", { name: "Missed five", exact: true })
      .waitFor();
    assert.equal(
      await page.getByRole("link", { name: "Recent two", exact: true }).count(),
      1,
    );
  }),
);
await test(
  "Local downloaded model remains selectable without a serving worker",
  at("/inference?model=base", async ({ page, state }) => {
    state.connections = [];
    state.workers = [{
      ...state.workers[0],
      capabilities: ["chat", "model_import"],
      resources: { gpus: [] },
    }];
    await page.reload();
    await page.getByText(/Connected workers report no GPU/).waitFor();
    assert.equal(
      await page.getByLabel("Model A", { exact: true }).inputValue(),
      "artifact:base",
    );
    assert.equal(
      await page.getByRole("button", { name: "Start for chat", exact: true })
        .isDisabled(),
      true,
    );
    await page.locator("#chat-prompt").fill(
      "Keep this draft while I connect an API",
    );
    assert.equal(
      await page.getByRole("button", { name: "Send", exact: true })
        .isDisabled(),
      true,
    );
    assert.equal(
      state.requests.filter((r) =>
        r.method === "POST" && r.path === "/deployments"
      ).length,
      0,
    );
    await page.screenshot({
      path: join(output, "inference-local-no-gpu.png"),
      fullPage: true,
    });
    await page.getByRole("link", { name: "Connect an API", exact: true })
      .click();
    await page.getByLabel("API base URL").waitFor();
    await page.getByRole("link", { name: "Return to draft", exact: true })
      .click();
    await page.getByText(/Connected workers report no GPU/).waitFor();
    assert.equal(
      await page.locator("#chat-prompt").inputValue(),
      "Keep this draft while I connect an API",
    );
  }),
);
await test(
  "Local base model starts without training and becomes chat-ready without losing its draft",
  at("/inference?model=base", async ({ page, state }) => {
    state.connections = [];
    await page.reload();
    await page.locator("#chat-prompt").fill("Explain this query plan");
    await page.getByRole("button", { name: "Start for chat", exact: true })
      .click();
    await page.getByText(/Server requested and waiting for a worker/).waitFor();
    const server = state.deployments[0];
    assert.equal(server.config.artifact_id, "base");
    assert.equal(server.config.tool_parser, "");
    assert.equal(
      state.requests.filter((r) =>
        r.method === "POST" && r.path === "/training-runs"
      ).length,
      0,
    );
    await page.reload();
    await page.getByText(/Server requested and waiting for a worker/).waitFor();
    assert.equal(
      await page.locator("#chat-prompt").inputValue(),
      "Explain this query plan",
    );
    assert.equal(
      await page.getByRole("button", { name: "Send", exact: true })
        .isDisabled(),
      true,
    );
    server.status = "running";
    server.result = { connection_id: "local" };
    state.connections.push({
      ...connection("local", "Local base server"),
      managed_job_id: server.id,
      artifact_id: "base",
    });
    await page.waitForFunction(
      () =>
        ![...document.querySelectorAll("button")].find((b) =>
          b.textContent === "Send"
        )?.disabled,
      { timeout: 12000 },
    );
    assert.equal(
      await page.getByLabel("Model A", { exact: true }).inputValue(),
      "artifact:base",
    );
    assert.equal(
      await page.getByRole("button", { name: "Start for chat", exact: true })
        .count(),
      0,
    );
    await page.screenshot({
      path: join(output, "inference-local-ready.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.locator(".conversation-turn").waitFor();
    assert.deepEqual(state.conversations[0].config.connection_ids, ["local"]);
    assert.equal(
      state.conversations[0].turns[0].prompt,
      "Explain this query plan",
    );
    assert.equal(
      state.requests.filter((r) =>
        r.method === "POST" && r.path === "/deployments"
      ).length,
      1,
    );
  }),
);
await test(
  "Local startup failure offers retry and reconciles a server started in another tab",
  at("/inference?model=base", async ({ page, state }) => {
    state.connections = [];
    await page.reload();
    await page.getByRole("button", { name: "Start for chat", exact: true })
      .click();
    await page.getByText(/Server requested and waiting for a worker/).waitFor();
    state.deployments[0].status = "failed";
    state.deployments[0].error = "Model could not fit in GPU memory";
    await page.getByRole("alert").filter({ hasText: "Model could not fit" })
      .waitFor({ timeout: 12000 });
    assert.equal(
      await page.getByRole("button", { name: "Start for chat", exact: true })
        .isEnabled(),
      true,
    );
    const other = {
      ...job("other-7", "Started elsewhere", "queued", "deployment"),
      config: { artifact_id: "base" },
      result: null,
    };
    state.deployments.unshift(other);
    state.jobs.unshift(other);
    await page.getByRole("button", { name: "Start for chat", exact: true })
      .click();
    await page.getByText(/Server requested and waiting for a worker/).waitFor();
    assert.equal(
      state.requests.filter((r) =>
        r.method === "POST" && r.path === "/deployments"
      ).length,
      1,
    );
    assert.equal(
      await page.getByRole("alert").filter({ hasText: "Model could not fit" })
        .count(),
      0,
    );
  }),
);
await test(
  "Local ready model reuses its existing connection and old connection links",
  at("/inference", async ({ page, state }) => {
    const server = {
      ...job("ready-9", "Ready base", "running", "deployment"),
      config: { artifact_id: "base" },
      result: { connection_id: "local" },
    };
    state.deployments = [server];
    state.connections = [{
      ...connection("local", "Ready base"),
      managed_job_id: server.id,
      artifact_id: "base",
    }];
    await page.goto(origin + "/inference?connection=local");
    await page.waitForFunction(() =>
      document.querySelector(".chat-model-bar select")?.value ===
        "artifact:base"
    );
    assert.equal(
      await page.locator(".chat-model-bar select").first().locator(
        "option[value='local']",
      ).count(),
      0,
    );
    await page.locator("#chat-prompt").fill("Chat with the existing server");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.locator(".conversation-turn").waitFor();
    assert.equal(
      state.requests.filter((r) =>
        r.method === "POST" && r.path === "/deployments"
      ).length,
      0,
    );
    assert.deepEqual(state.conversations[0].config.connection_ids, ["local"]);
  }),
);
await test(
  "Local model and trained variant are both selectable; one-worker A/B has an actionable limit",
  at("/inference?model=base", async ({ page, state }) => {
    state.artifacts.push({
      ...state.artifacts[0],
      id: "adapter",
      kind: "adapter",
      name: "Trained variant",
      metadata: { base_artifact_id: "base" },
    });
    await page.reload();
    await page.getByLabel("Model B · optional").selectOption(
      "artifact:adapter",
    );
    await page.getByText(/Two local models need two serving workers/).waitFor();
    const launchButtons = page.getByRole("button", {
      name: "Start for chat",
      exact: true,
    });
    assert.equal(await launchButtons.count(), 2);
    assert.equal(await launchButtons.first().isDisabled(), true);
    assert.equal(await launchButtons.last().isDisabled(), true);
    await page.getByLabel("Model A", { exact: true }).selectOption("a");
    await page.getByRole("button", { name: "Start for chat", exact: true })
      .click();
    await page.getByText(/Server requested and waiting for a worker/).waitFor();
    assert.equal(state.deployments[0].config.artifact_id, "adapter");
  }, 390),
);
await test(
  "Local server with a lost worker never reports that it is chat-ready",
  at("/inference?model=base", async ({ page, state }) => {
    state.connections = [];
    state.deployments = [{
      ...job("lost-8", "Disconnected server", "running", "deployment"),
      worker_connected: false,
      config: { artifact_id: "base" },
      result: { connection_id: "old" },
    }];
    await page.reload();
    await page.getByText(/Contact with the server worker was lost/).waitFor();
    assert.equal(await page.getByText(/Server ready. Connecting/).count(), 0);
    assert.equal(
      await page.getByRole("button", { name: "Start for chat", exact: true })
        .count(),
      0,
    );
    await page.locator("#chat-prompt").fill("Can you hear me?");
    assert.equal(
      await page.getByRole("button", { name: "Send", exact: true })
        .isDisabled(),
      true,
    );
  }),
);
await test(
  "Local model links cannot select the same model twice through an old A/B connection draft",
  at("/inference", async ({ page, state }) => {
    const server = {
      ...job("ready-9", "Ready base", "running", "deployment"),
      config: { artifact_id: "base" },
      result: { connection_id: "local" },
    };
    state.deployments = [server];
    state.connections.push({
      ...connection("local", "Ready base"),
      managed_job_id: server.id,
      artifact_id: "base",
    });
    await page.evaluate(() =>
      sessionStorage.setItem(
        "pg-workspace:chat-settings",
        JSON.stringify({ a: "a", b: "local" }),
      )
    );
    await page.goto(origin + "/inference?model=base");
    await page.waitForFunction(() =>
      document.querySelector(".chat-model-bar select")?.value ===
        "artifact:base"
    );
    assert.equal(await page.getByLabel("Model B · optional").inputValue(), "");
    await page.locator("#chat-prompt").fill("Use the selected model once");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.locator(".conversation-turn").waitFor();
    assert.deepEqual(state.conversations[0].config.connection_ids, ["local"]);
    assert.equal(await page.locator(".response-cell:visible").count(), 1);
  }),
);
await writeFile(join(output, "results.json"), JSON.stringify(results, null, 2));
await browser.close();
await new Promise((r) => server.close(r));
console.log(
  `${
    results.filter((r) => r.status === "passed").length
  }/${results.length} passed; output ${output}`,
);
if (results.some((r) => r.status === "failed")) process.exitCode = 1;
