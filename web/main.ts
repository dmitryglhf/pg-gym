import { App, staticFiles } from "fresh";

const base = (Deno.env.get("PG_GYM_API_URL") || "http://127.0.0.1:9433")
  .replace(/\/$/, "");
export const app = new App()
  .use(async (ctx) => {
    const path = ctx.url.pathname;
    if (path.startsWith("/api/v1/")) {
      const headers = new Headers(ctx.req.headers);
      headers.delete("host");
      headers.delete("connection");
      headers.delete("content-length");
      try {
        const response = await fetch(base + path + ctx.url.search, {
          method: ctx.req.method,
          headers,
          body: ["GET", "HEAD"].includes(ctx.req.method)
            ? undefined
            : ctx.req.body,
          redirect: "manual",
          signal: ctx.req.signal,
        });
        const out = new Headers(response.headers);
        out.delete("transfer-encoding");
        out.delete("content-length");
        out.delete("content-encoding");
        return new Response(response.body, {
          status: response.status,
          headers: out,
        });
      } catch {
        return Response.json({
          error: {
            code: "unavailable",
            message: "The platform API is unavailable",
          },
        }, { status: 503 });
      }
    }
    const query = ctx.url.searchParams;
    let legacyTarget: string | null = null;
    if (path === "/console") {
      legacyTarget = "/?panel=console" +
        (query.get("job")
          ? "&job=" + encodeURIComponent(query.get("job")!)
          : "");
    }
    if (
      path === "/settings" &&
      ["connections", "environment"].includes(query.get("tab") || "")
    ) {
      legacyTarget = "/models" +
        (query.get("tab") === "environment" ? "?section=keys" : "");
    }
    if (path === "/settings" && query.get("tab") === "harnesses") {
      legacyTarget = "/benchmark#profiles";
    }
    if (
      path === "/inference" &&
      (["models", "servers"].includes(query.get("tab") || "") ||
        query.has("artifact"))
    ) {
      legacyTarget = "/models" +
        (query.get("artifact")
          ? "?artifact=" + encodeURIComponent(query.get("artifact")!)
          : "");
    }
    if (legacyTarget) {
      return Response.redirect(new URL(legacyTarget, ctx.url), 303);
    }
    if (path === "/run") {
      return Response.redirect(
        new URL("/benchmark" + ctx.url.search, ctx.url),
        308,
      );
    }
    if (
      path !== "/login" &&
      !["/assets/", "/_fresh/", "/_frsh/", "/favicon"].some((prefix) =>
        path.startsWith(prefix)
      )
    ) {
      try {
        const response = await fetch(base + "/api/v1/me", {
          headers: { cookie: ctx.req.headers.get("cookie") || "" },
          signal: AbortSignal.timeout(10000),
        });
        await response.body?.cancel();
        if (response.status === 401) {
          return Response.redirect(
            new URL(
              "/login?next=" +
                encodeURIComponent(ctx.url.pathname + ctx.url.search),
              ctx.url,
            ),
            303,
          );
        }
        if (!response.ok) {
          return new Response("Platform unavailable. Reload to retry.", {
            status: 503,
          });
        }
      } catch {
        return new Response("Platform unavailable. Reload to retry.", {
          status: 503,
        });
      }
    }
    const response = await ctx.next();
    response.headers.set("X-Frame-Options", "DENY");
    response.headers.set("X-Content-Type-Options", "nosniff");
    response.headers.set("Referrer-Policy", "same-origin");
    response.headers.set("Cache-Control", "no-store");
    return response;
  })
  .use(staticFiles())
  .fsRoutes();

if (import.meta.main) await app.listen();
