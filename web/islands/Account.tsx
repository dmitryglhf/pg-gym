import { SignOut } from "@/components/SignOut.tsx";
import { Icon } from "@/components/Icon.tsx";
export default function Account({ pathname }: { pathname: string }) {
  return (
    <div class="rail-account">
      <a
        href="/settings"
        class="account-settings"
        aria-current={pathname === "/settings" ? "page" : undefined}
      >
        <Icon name="settings" size={22} />
        <span>Settings</span>
      </a>
      <SignOut />
    </div>
  );
}
