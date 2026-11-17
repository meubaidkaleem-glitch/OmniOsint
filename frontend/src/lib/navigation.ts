/**
 * The navigation structure of the brief (section 13.2), defined once.
 *
 * Whether a section is built comes from the backend feature registry
 * (GET /system/features), never from this file.
 */
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BellRing,
  Boxes,
  BrainCircuit,
  Bug,
  FileSearch,
  FolderKanban,
  Globe2,
  History,
  LayoutDashboard,
  Network,
  PlugZap,
  Radar,
  Search,
  Server,
  Settings,
  Share2,
  ShieldAlert,
  UserSearch,
  Users,
} from "lucide-react";

export type NavGroup = "Intelligence" | "Analysis" | "Operations" | "Platform";

export interface NavSection {
  /** Feature key in the backend registry. */
  key: string;
  title: string;
  path: string;
  icon: LucideIcon;
  group: NavGroup | null;
  /** Permission needed to see the section (none means any signed-in user). */
  permission?: string;
}

export const NAV_SECTIONS: NavSection[] = [
  { key: "dashboard", title: "Dashboard", path: "/", icon: LayoutDashboard, group: null },
  { key: "universal_search", title: "Universal Search", path: "/search", icon: Search, group: null },
  {
    key: "investigations",
    title: "Investigations",
    path: "/investigations",
    icon: FolderKanban,
    group: null,
  },
  {
    key: "identity",
    title: "Identity Intelligence",
    path: "/identity",
    icon: UserSearch,
    group: "Intelligence",
  },
  {
    key: "infrastructure",
    title: "Infrastructure Intelligence",
    path: "/infrastructure",
    icon: Server,
    group: "Intelligence",
  },
  {
    key: "internet_assets",
    title: "Internet Asset Intelligence",
    path: "/internet-assets",
    icon: Radar,
    group: "Intelligence",
  },
  {
    key: "network_topology",
    title: "Network Topology",
    path: "/network-topology",
    icon: Network,
    group: "Intelligence",
  },
  { key: "threat", title: "Threat Intelligence", path: "/threat", icon: ShieldAlert, group: "Intelligence" },
  {
    key: "social_media",
    title: "Social and Media Intelligence",
    path: "/social-media",
    icon: Users,
    group: "Intelligence",
  },
  {
    key: "image_document",
    title: "Image and Document Intelligence",
    path: "/image-document",
    icon: FileSearch,
    group: "Intelligence",
  },
  {
    key: "geospatial",
    title: "Geospatial Intelligence",
    path: "/geospatial",
    icon: Globe2,
    group: "Intelligence",
  },
  {
    key: "software_supply_chain",
    title: "Software and Supply Chain",
    path: "/software-supply-chain",
    icon: Boxes,
    group: "Intelligence",
  },
  {
    key: "vulnerability",
    title: "Vulnerability Intelligence",
    path: "/vulnerability",
    icon: Bug,
    group: "Intelligence",
  },
  {
    key: "relationship_graph",
    title: "Relationship Graph",
    path: "/graph",
    icon: Share2,
    group: "Analysis",
  },
  {
    key: "historical",
    title: "Historical Intelligence",
    path: "/historical",
    icon: History,
    group: "Analysis",
  },
  {
    key: "ai_investigation",
    title: "AI Investigation Center",
    path: "/ai",
    icon: BrainCircuit,
    group: "Analysis",
  },
  {
    key: "monitoring",
    title: "Monitoring and Alerts",
    path: "/monitoring",
    icon: BellRing,
    group: "Operations",
  },
  {
    key: "reports_evidence",
    title: "Reports and Evidence",
    path: "/reports",
    icon: Activity,
    group: "Operations",
  },
  { key: "integrations", title: "Integrations", path: "/integrations", icon: PlugZap, group: "Platform" },
  {
    key: "administration",
    title: "Administration and Settings",
    path: "/admin",
    icon: Settings,
    group: "Platform",
  },
];

export const NAV_GROUPS: NavGroup[] = ["Intelligence", "Analysis", "Operations", "Platform"];

export interface AdminPage {
  path: string;
  title: string;
  permission?: string;
}

export const ADMIN_PAGES: AdminPage[] = [
  { path: "/admin/account", title: "My account" },
  { path: "/admin/users", title: "Users", permission: "users:read" },
  { path: "/admin/roles", title: "Roles", permission: "roles:read" },
  { path: "/admin/audit", title: "Audit log", permission: "audit:read" },
  { path: "/admin/system", title: "System status", permission: "system:read" },
];

export function canSee(permission: string | undefined, permissions: readonly string[]): boolean {
  return permission === undefined || permissions.includes(permission);
}

export function sectionForPath(pathname: string): NavSection | undefined {
  if (pathname === "/") return NAV_SECTIONS[0];
  return NAV_SECTIONS.find(
    (section) => section.path !== "/" && (pathname === section.path || pathname.startsWith(`${section.path}/`)),
  );
}
