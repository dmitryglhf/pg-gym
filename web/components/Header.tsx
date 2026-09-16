import { Icon } from "./Icon.tsx";
import Account from "@/islands/Account.tsx";

export function Header({ pathname }: { pathname: string }) {
  const links = [
    {
      href: "/",
      label: "Workspace",
      icon: "home" as const,
      active: pathname === "/" || pathname.startsWith("/results") ||
        pathname.startsWith("/jobs") || pathname === "/console",
    },
    {
      href: "/models",
      label: "Models & servers",
      icon: "layers" as const,
      active: pathname.startsWith("/models"),
    },
    {
      href: "/inference",
      label: "Inference",
      icon: "chat" as const,
      active: pathname.startsWith("/inference"),
    },
    {
      href: "/benchmark",
      label: "Benchmarks",
      icon: "play" as const,
      active: pathname.startsWith("/benchmark"),
    },
    {
      href: "/rl",
      label: "Training",
      icon: "training" as const,
      active: pathname.startsWith("/rl"),
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
