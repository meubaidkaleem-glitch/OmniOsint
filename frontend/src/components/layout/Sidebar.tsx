import { ChevronDown, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { NavLink } from "react-router";

import type { FeatureOut } from "@/api/types";
import { cn } from "@/lib/format";
import { NAV_GROUPS, NAV_SECTIONS, type NavSection, canSee } from "@/lib/navigation";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { useUiStore } from "@/stores/ui";

function SectionLink({
  section,
  feature,
  collapsed,
}: {
  section: NavSection;
  feature: FeatureOut | undefined;
  collapsed: boolean;
}) {
  const Icon = section.icon;
  const planned = feature?.status === "planned";
  return (
    <NavLink
      to={section.path}
      end={section.path === "/"}
      title={planned ? `${section.title} (planned, Phase ${feature?.phase})` : section.title}
      className={({ isActive }) =>
        cn(
          "group flex h-[30px] items-center gap-2.5 rounded-md px-2.5 text-[13px] transition-colors",
          isActive
            ? "bg-accent-soft text-fg"
            : planned
              ? "text-fg-subtle hover:bg-surface-3 hover:text-fg-muted"
              : "text-fg-muted hover:bg-surface-3 hover:text-fg",
          collapsed && "justify-center px-0",
        )
      }
      data-feature-status={feature?.status ?? "unknown"}
    >
      {({ isActive }) => (
        <>
          <Icon className={cn("size-4 shrink-0", isActive && "text-accent")} aria-hidden />
          {!collapsed ? (
            <>
              <span className="min-w-0 flex-1 truncate">{section.title}</span>
              {planned ? (
                <span className="text-[10px] uppercase tracking-wide text-fg-subtle/80" aria-label="planned">
                  P{feature?.phase}
                </span>
              ) : null}
            </>
          ) : null}
        </>
      )}
    </NavLink>
  );
}

export function Sidebar({
  features,
  permissions,
}: {
  features: Map<string, FeatureOut>;
  permissions: readonly string[];
}) {
  const { sidebarCollapsed, toggleSidebar, closedGroups, toggleGroup } = useUiStore();
  // Narrow windows always get the icon rail so the page keeps its width.
  const narrow = useMediaQuery("(max-width: 1023px)");
  const collapsed = narrow || sidebarCollapsed;
  const visible = NAV_SECTIONS.filter((section) => canSee(section.permission, permissions));
  const ungrouped = visible.filter((section) => section.group === null);

  return (
    <nav
      aria-label="Main navigation"
      className={cn(
        "flex h-full shrink-0 flex-col border-r border-line bg-surface transition-[width]",
        collapsed ? "w-14" : "w-66",
      )}
    >
      <div className={cn("flex h-13 items-center gap-2.5 border-b border-line px-3.5", collapsed && "justify-center px-0")}>
        <img src="/favicon.svg" alt="" className="size-6" />
        {!collapsed ? (
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-tight text-fg">OmniOSINT</div>
            <div className="text-[10px] uppercase tracking-wider text-fg-subtle">Intelligence platform</div>
          </div>
        ) : null}
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-2 py-2.5">
        <div className="space-y-0.5">
          {ungrouped.map((section) => (
            <SectionLink
              key={section.key}
              section={section}
              feature={features.get(section.key)}
              collapsed={collapsed}
            />
          ))}
        </div>
        {NAV_GROUPS.map((group) => {
          const items = visible.filter((section) => section.group === group);
          if (!items.length) return null;
          const closed = closedGroups.includes(group) && !collapsed;
          return (
            <div key={group}>
              {!collapsed ? (
                <button
                  type="button"
                  onClick={() => toggleGroup(group)}
                  aria-expanded={!closed}
                  className="mb-1 flex w-full items-center justify-between px-2.5 text-[10px] font-semibold uppercase tracking-wider text-fg-subtle hover:text-fg-muted"
                >
                  {group}
                  <ChevronDown className={cn("size-3 transition-transform", closed && "-rotate-90")} aria-hidden />
                </button>
              ) : (
                <div className="mx-3 mb-1 h-px bg-line" />
              )}
              {!closed ? (
                <div className="space-y-0.5">
                  {items.map((section) => (
                    <SectionLink
                      key={section.key}
                      section={section}
                      feature={features.get(section.key)}
                      collapsed={collapsed}
                    />
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      <button
        type="button"
        hidden={narrow}
        onClick={toggleSidebar}
        className={cn(
          "flex h-10 items-center gap-2 border-t border-line px-3.5 text-xs text-fg-subtle hover:text-fg",
          collapsed && "justify-center px-0",
        )}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
        {!collapsed ? "Collapse" : null}
      </button>
    </nav>
  );
}
