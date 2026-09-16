import { define } from "@/utils.ts";
export default define.page(({ Component }) => (
  <html lang="en">
    <head>
      <meta charSet="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>Postgres Gym</title>
    </head>
    <body>
      <Component />
    </body>
  </html>
));
