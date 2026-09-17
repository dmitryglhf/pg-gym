# Browser UX regression review

This runner bundles the production Preact components and styles and mounts them in
Chromium. A local HTTP server serves the bundle; Playwright supplies stateful API
fixtures. It does not start Fresh, Python, Docker, a GPU or a real model endpoint.

```sh
cd web/tests/browser
npm install
npx playwright install chromium
npm run review
```

Requires Node.js 20.19+ and a supported Chromium runtime. Dependencies are isolated
from the frontend's Deno setup. Set `UI_CHROMIUM_EXECUTABLE` to use an installed
Chromium binary. `UI_REVIEW_OUTPUT` selects the results directory (default:
`review-output` beside `web/`). Output includes `results.json` and screenshots.

Coverage includes floating monochrome navigation, mobile layout, draft restoration,
stream cursor stability, pending chat submissions, connection key editing, retained
pagination rows, changing console lists, missing model links, invalid hidden inputs,
malformed submit acknowledgements and login return URLs. Run against real services
separately to verify routing, sessions, CSRF, workers and model execution.

Local-model coverage includes downloaded base models and trained adapters, missing
serving workers, startup to readiness, failed startup recovery, existing-server reuse,
legacy connection links, lost worker contact and duplicate A/B selection.
Set `UI_REVIEW_CASE` to a case-insensitive regular expression to run a focused subset.
