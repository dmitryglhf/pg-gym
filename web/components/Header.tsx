import { Icon } from "./Icon.tsx";
import Account from "@/islands/Account.tsx";

export function Header({ pathname }: { pathname: string }) {
  const links = [
    {
      href: "/",
      label: "Workspace",
      icon: "home" as const,
      active: pathname === "/",
    },
    {
      href: "/benchmark",
      label: "Benchmark",
      icon: "play" as const,
      active: pathname === "/benchmark",
    },
    {
      href: "/results",
      label: "Results",
      icon: "chart" as const,
      active: pathname.startsWith("/results") || pathname.startsWith("/jobs"),
    },
    {
      href: "/rl",
      label: "RL",
      icon: "training" as const,
      active: pathname.startsWith("/rl"),
    },
    {
      href: "/inference",
      label: "Inference",
      icon: "chat" as const,
      active: pathname.startsWith("/inference"),
    },
    {
      href: "/console",
      label: "Console",
      icon: "terminal" as const,
      active: pathname === "/console",
    },
  ];
  return (
    <>
      <a class="skip-link" href="#main-content">Skip to content</a>
      <header class="tool-rail">
        <nav class="tool-nav" aria-label="Primary navigation">
          {links.map((link) => (
            <a
              href={link.href}
              key={link.href}
              aria-current={link.active ? "page" : undefined}
            >
              <span class="nav-icon">
                <Icon name={link.icon} size={24} />
              </span>
              <span>{link.label}</span>
            </a>
          ))}
        </nav>
        <Account pathname={pathname} />
      </header>
    </>
  );
}
