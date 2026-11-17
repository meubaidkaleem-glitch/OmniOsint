import { Navigate, createBrowserRouter, type RouteObject } from "react-router";

import { useShell } from "@/app/context";
import { NAV_SECTIONS } from "@/lib/navigation";
import { DashboardPage } from "@/pages/DashboardPage";
import { IntegrationsPage } from "@/pages/IntegrationsPage";
import { NotFoundPage } from "@/pages/MiscPages";
import { PlannedPage } from "@/pages/PlannedPage";
import { AccountPage } from "@/pages/admin/AccountPage";
import { AdminLayout } from "@/pages/admin/AdminLayout";
import { AuditPage } from "@/pages/admin/AuditPage";
import { RolesPage } from "@/pages/admin/RolesPage";
import { SystemPage } from "@/pages/admin/SystemPage";
import { UsersPage } from "@/pages/admin/UsersPage";
import { ChangePasswordPage } from "@/pages/auth/ChangePasswordPage";
import { LoginPage } from "@/pages/auth/LoginPage";
import { SetupPage } from "@/pages/auth/SetupPage";

import { RequireAuth } from "./RequireAuth";

/** Sections with their own page; every other section shows the planned page. */
const BUILT_SECTIONS = new Set(["dashboard", "integrations", "administration"]);

function AdminIndex() {
  const { me } = useShell();
  return <Navigate to={me.permissions.includes("users:read") ? "/admin/users" : "/admin/account"} replace />;
}

export const routes: RouteObject[] = [
  { path: "/setup", element: <SetupPage /> },
  { path: "/login", element: <LoginPage /> },
  { path: "/change-password", element: <ChangePasswordPage /> },
  {
    element: <RequireAuth />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "integrations", element: <IntegrationsPage /> },
      {
        path: "admin",
        element: <AdminLayout />,
        children: [
          { index: true, element: <AdminIndex /> },
          { path: "account", element: <AccountPage /> },
          { path: "users", element: <UsersPage /> },
          { path: "roles", element: <RolesPage /> },
          { path: "audit", element: <AuditPage /> },
          { path: "system", element: <SystemPage /> },
        ],
      },
      ...NAV_SECTIONS.filter((section) => !BUILT_SECTIONS.has(section.key)).map((section) => ({
        path: `${section.path.slice(1)}/*`,
        element: <PlannedPage section={section} />,
      })),
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export function createRouter() {
  return createBrowserRouter(routes);
}
