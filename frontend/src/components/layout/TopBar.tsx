import { LogOut, Moon, Search, Sun, UserRound } from "lucide-react";
import { useNavigate } from "react-router";

import { useLogout, useReadiness } from "@/api/queries";
import type { AuthState } from "@/api/types";
import { Kbd, StatusDot, statusLabel } from "@/components/ui/surface";
import {
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuRoot,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/overlay";
import { useUiStore } from "@/stores/ui";

function HealthIndicator() {
  const navigate = useNavigate();
  const { data, isError } = useReadiness();
  const status = isError ? "unavailable" : (data?.status ?? null);
  if (status === null) return null;
  const label = `System status: ${statusLabel(status)}`;
  return (
    <button
      type="button"
      onClick={() => navigate("/")}
      className="flex h-8 items-center gap-2 rounded-md px-2.5 text-xs text-fg-muted hover:bg-surface-3 hover:text-fg"
      title={label}
      aria-label={label}
    >
      <StatusDot status={status} />
      <span className="hidden md:inline">{statusLabel(status)}</span>
    </button>
  );
}

export function TopBar({ me }: { me: AuthState }) {
  const navigate = useNavigate();
  const logout = useLogout();
  const { theme, toggleTheme, setPaletteOpen } = useUiStore();
  const initials = me.user.display_name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <header className="flex h-13 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
      <button
        type="button"
        onClick={() => setPaletteOpen(true)}
        className="flex h-8 w-full max-w-md items-center gap-2 rounded-md border border-line-strong bg-surface-2 px-3 text-sm text-fg-subtle transition-colors hover:border-accent/50 hover:text-fg-muted"
      >
        <Search className="size-4" aria-hidden />
        <span className="flex-1 text-left">Jump to a section or action…</span>
        <Kbd>Ctrl K</Kbd>
      </button>

      <div className="ml-auto flex items-center gap-1">
        <HealthIndicator />
        <MenuRoot>
          <MenuTrigger asChild>
            <button
              type="button"
              className="flex h-8 items-center gap-2 rounded-md px-1.5 text-sm text-fg-muted hover:bg-surface-3 hover:text-fg"
              aria-label="Account menu"
            >
              <span className="flex size-6 items-center justify-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent">
                {initials || <UserRound className="size-3.5" />}
              </span>
              <span className="hidden max-w-40 truncate lg:inline">{me.user.display_name}</span>
            </button>
          </MenuTrigger>
          <MenuContent>
            <MenuLabel>
              Signed in as <span className="font-medium text-fg">{me.user.username}</span>
              <span className="block">{me.user.roles.join(", ")}</span>
            </MenuLabel>
            <MenuSeparator />
            <MenuItem icon={<UserRound className="size-4" />} onSelect={() => navigate("/admin/account")}>
              My account
            </MenuItem>
            <MenuItem
              icon={theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
              onSelect={toggleTheme}
            >
              {theme === "dark" ? "Light theme" : "Dark theme"}
            </MenuItem>
            <MenuSeparator />
            <MenuItem
              icon={<LogOut className="size-4" />}
              onSelect={() => logout.mutate(undefined, { onSettled: () => navigate("/login") })}
            >
              Sign out
            </MenuItem>
          </MenuContent>
        </MenuRoot>
      </div>
    </header>
  );
}
