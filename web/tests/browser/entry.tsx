// Browser fixture mounts the production components; only API replies are stubbed by the runner.
import { render } from "preact";
import { Header } from "../../components/Header.tsx";
import Platform from "../../islands/Platform.tsx";
import ActivityDock from "../../islands/ActivityDock.tsx";
import Login from "../../islands/Login.tsx";
import "../../assets/shared.css";
import "../../assets/platform.css";
import "../../assets/workspace.css";
const pathname = location.pathname;
const page = ({
  "/": "home",
  "/models": "models",
  "/benchmark": "benchmark",
  "/rl": "rl",
  "/results": "results",
  "/inference": "inference",
  "/settings": "settings",
} as Record<string, string>)[pathname] || "home";
render(
  pathname === "/login" ? <Login /> : (
    <div class="page-shell">
      <Header pathname={pathname} />
      <Platform
        page={page}
        id={pathname.startsWith("/jobs/") ? pathname.split("/")[2] : undefined}
      />
      <ActivityDock />
    </div>
  ),
  document.getElementById("app")!,
);
