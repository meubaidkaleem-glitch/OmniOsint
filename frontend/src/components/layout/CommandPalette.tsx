import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Command } from "cmdk";
import { CornerDownLeft, LogOut, Moon, Search, Settings, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { useLogout } from "@/api/queries";
import type { FeatureOut } from "@/api/types";
import { ADMIN_PAGES, NAV_SECTIONS, canSee } from "@/lib/navigation";
import { useUiStore } from "@/stores/ui";

const ITEM =
  "flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-fg-muted " +
  "data-[selected=true]:bg-surface-3 data-[selected=true]:text-fg";

/** Keyboard-driven navigation (Ctrl+K / Cmd+K). */
export function CommandPalette({
  features,
  permissions,
}: {
  features: Map<string, FeatureOut>;
  permissions: readonly string[];
}) {
  const navigate = useNavigate();
  const logout = useLogout();
  const { paletteOpen: open, setPaletteOpen: setOpen, theme, toggleTheme } = useUiStore();

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(!useUiStore.getState().paletteOpen);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [setOpen]);

  function run(action: () => void) {
    setOpen(false);
    action();
  }

  const [query, setQuery] = useState("");
  const canSearch = permissions.includes("collection:read");
  const sections = NAV_SECTIONS.filter((section) => canSee(section.permission, permissions));
  const adminPages = ADMIN_PAGES.filter((page) => canSee(page.permission, permissions));

  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(value) => {
        setOpen(value);
        if (!value) setQuery("");
      }}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <DialogPrimitive.Content
          className="fixed left-1/2 top-[14vh] z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-lg border border-line-strong bg-surface shadow-2xl shadow-black/40"
          aria-describedby={undefined}
        >
          <DialogPrimitive.Title className="sr-only">Command palette</DialogPrimitive.Title>
          <Command label="Command palette" loop>
            <Command.Input
              autoFocus
              value={query}
              onValueChange={setQuery}
              placeholder={canSearch ? "Type an indicator, a section or an action…" : "Type a section or action…"}
              className="h-12 w-full border-b border-line bg-transparent px-4 text-sm text-fg placeholder:text-fg-subtle focus:outline-none"
            />
            <Command.List className="max-h-[50vh] overflow-y-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-sm text-fg-subtle">
                No matching section or action.
              </Command.Empty>
              <Command.Group
                heading="Sections"
                className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-fg-subtle"
              >
                {sections.map((section) => {
                  const feature = features.get(section.key);
                  const Icon = section.icon;
                  return (
                    <Command.Item
                      key={section.key}
                      value={`${section.title} ${section.key}`}
                      onSelect={() => run(() => navigate(section.path))}
                      className={ITEM}
                    >
                      <Icon className="size-4 shrink-0" aria-hidden />
                      <span className="flex-1">{section.title}</span>
                      {feature?.status === "planned" ? (
                        <span className="text-xs text-fg-subtle">Planned · Phase {feature.phase}</span>
                      ) : null}
                    </Command.Item>
                  );
                })}
              </Command.Group>
              <Command.Group
                heading="Administration"
                className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-fg-subtle"
              >
                {adminPages.map((page) => (
                  <Command.Item
                    key={page.path}
                    value={`Administration ${page.title}`}
                    onSelect={() => run(() => navigate(page.path))}
                    className={ITEM}
                  >
                    <Settings className="size-4 shrink-0" aria-hidden />
                    {page.title}
                  </Command.Item>
                ))}
              </Command.Group>
              <Command.Group
                heading="Actions"
                className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-fg-subtle"
              >
                <Command.Item value="Toggle theme light dark" onSelect={() => run(toggleTheme)} className={ITEM}>
                  {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
                  Switch to {theme === "dark" ? "light" : "dark"} theme
                </Command.Item>
                <Command.Item
                  value="Sign out log out"
                  onSelect={() => run(() => logout.mutate(undefined, { onSettled: () => navigate("/login") }))}
                  className={ITEM}
                >
                  <LogOut className="size-4" />
                  Sign out
                </Command.Item>
              </Command.Group>
              {canSearch && query.trim() ? (
                <Command.Group
                  forceMount
                  heading="Universal Search"
                  className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-fg-subtle"
                >
                  <Command.Item
                    forceMount
                    value="universal-search-entry"
                    onSelect={() => run(() => navigate(`/search?q=${encodeURIComponent(query.trim())}`))}
                    className={ITEM}
                  >
                    <Search className="size-4 shrink-0" aria-hidden />
                    <span className="min-w-0 flex-1 truncate">
                      Search for <span className="text-fg">{query.trim()}</span>
                    </span>
                  </Command.Item>
                </Command.Group>
              ) : null}
            </Command.List>
            <div className="flex items-center gap-3 border-t border-line px-4 py-2 text-[11px] text-fg-subtle">
              <span className="flex items-center gap-1">
                <CornerDownLeft className="size-3" /> select
              </span>
              <span>↑↓ move</span>
              <span>Esc close</span>
              {canSearch ? <span className="ml-auto">Type an indicator to search for it</span> : null}
            </div>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
