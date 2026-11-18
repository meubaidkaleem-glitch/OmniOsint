import { NavLink, Outlet } from "react-router";

import { useShell } from "@/app/context";
import { PageHeader } from "@/components/ui/surface";
import { cn } from "@/lib/format";

const TABS = [
  { path: "/search", title: "Search", end: true },
  { path: "/search/history", title: "Collection history", end: false },
];

export function SearchLayout() {
  const shell = useShell();
  return (
    <>
      <PageHeader
        title="Universal Search"
        description="Enter any indicator. OmniOSINT classifies it, shows what would be collected and why, and runs only what you approve."
      />
      <nav aria-label="Universal Search" className="mb-5 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map((tab) => (
          <NavLink
            key={tab.path}
            to={tab.path}
            end={tab.end}
            className={({ isActive }) =>
              cn(
                "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors",
                isActive ? "border-accent text-fg" : "border-transparent text-fg-muted hover:text-fg",
              )
            }
          >
            {tab.title}
          </NavLink>
        ))}
      </nav>
      <Outlet context={shell} />
    </>
  );
}
