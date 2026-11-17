import { NavLink, Outlet } from "react-router";

import { useShell } from "@/app/context";
import { PageHeader } from "@/components/ui/surface";
import { cn } from "@/lib/format";
import { ADMIN_PAGES, canSee } from "@/lib/navigation";

export function AdminLayout() {
  const shell = useShell();
  const pages = ADMIN_PAGES.filter((page) => canSee(page.permission, shell.me.permissions));
  return (
    <>
      <PageHeader
        title="Administration and Settings"
        description="Accounts, roles, the audit trail, system status and your own account."
      />
      <nav aria-label="Administration" className="mb-5 flex gap-1 overflow-x-auto border-b border-line">
        {pages.map((page) => (
          <NavLink
            key={page.path}
            to={page.path}
            className={({ isActive }) =>
              cn(
                "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors",
                isActive
                  ? "border-accent text-fg"
                  : "border-transparent text-fg-muted hover:text-fg",
              )
            }
          >
            {page.title}
          </NavLink>
        ))}
      </nav>
      <Outlet context={shell} />
    </>
  );
}
