import { define } from "@/utils.ts";
import { Header } from "@/components/Header.tsx";
export default define.layout(({ Component, url }) =>
  url.pathname === "/login" ? <Component /> : (
    <div class="page-shell">
      <Header pathname={url.pathname} />
      <Component />
    </div>
  )
);
