import type {
  AuthState,
  DashboardResponse,
  FeatureList,
  FeatureOut,
  ProviderList,
  ReadyResponse,
  UserOut,
} from "@/api/types";
import { NAV_SECTIONS } from "@/lib/navigation";

const NOW = "2026-11-17T10:00:00Z";

export function user(overrides: Partial<UserOut> = {}): UserOut {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    username: "admin",
    display_name: "Morgan Admin",
    email: null,
    is_active: true,
    must_change_password: false,
    roles: ["administrator"],
    locked_until: null,
    last_login_at: NOW,
    password_changed_at: NOW,
    created_at: NOW,
    updated_at: NOW,
    ...overrides,
  };
}

export const ADMIN_PERMISSIONS = [
  "audit:read",
  "collection:approve",
  "collection:read",
  "collection:run",
  "evidence:read",
  "evidence:read_raw",
  "roles:read",
  "scopes:manage",
  "scopes:read",
  "system:manage",
  "system:read",
  "users:manage",
  "users:read",
];

export function authState(
  overrides: { user?: Partial<UserOut>; permissions?: string[] } = {},
): AuthState {
  return {
    user: user(overrides.user),
    permissions: overrides.permissions ?? ADMIN_PERMISSIONS,
    session: { id: "00000000-0000-4000-8000-0000000000aa", auth_method: "cookie", expires_at: NOW },
    csrf_token: "csrf-test-token",
  };
}

const BUILT = new Map<string, FeatureOut["status"]>([
  ["dashboard", "partial"],
  ["universal_search", "partial"],
  ["integrations", "partial"],
  ["administration", "available"],
]);

export function featureList(): FeatureList {
  const features: FeatureOut[] = NAV_SECTIONS.map((section, index) => ({
    key: section.key,
    title: section.title,
    group: section.group,
    phase: BUILT.has(section.key) ? 1 : 2 + (index % 10),
    phase_title: "A phase",
    status: BUILT.get(section.key) ?? "planned",
    summary: `${section.title} summary.`,
    capabilities: [`${section.title} capability one`, `${section.title} capability two`],
    limitations: null,
  }));
  return {
    current_phase: 2,
    phases: [
      { number: 1, title: "Project foundation" },
      { number: 2, title: "Core intelligence foundation" },
    ],
    counts: { available: 1, partial: 3, planned: 16 },
    features,
  };
}

export function readiness(): ReadyResponse {
  return {
    status: "ok",
    checked_at: NOW,
    components: [{ name: "database", label: "PostgreSQL database", status: "ok", required: true }],
  };
}

export function dashboard(): DashboardResponse {
  return {
    generated_at: NOW,
    health: {
      status: "degraded",
      checked_at: NOW,
      components: [
        { name: "database", label: "PostgreSQL database", status: "ok", required: true, detail: "PostgreSQL 16." },
        { name: "redis", label: "Redis cache", status: "not_configured", required: false, detail: "Not configured." },
      ],
    },
    metrics: [
      { key: "users_active", label: "Active user accounts", available: true, value: 3, planned_phase: null, phase_title: null },
      { key: "sign_ins_24h", label: "Sign-ins, last 24 hours", available: true, value: 0, planned_phase: null, phase_title: null },
      { key: "investigations_total", label: "Total investigations", available: false, value: null, planned_phase: 3, phase_title: "Investigation management" },
      { key: "alerts_recent", label: "Recent alerts", available: false, value: null, planned_phase: 11, phase_title: "Monitoring" },
    ],
    modules: { available: 1, partial: 2, planned: 17 },
    providers: { total: 79, available: 0, planned: 75, excluded: 4 },
    recent_activity: [
      {
        id: "00000000-0000-7000-8000-000000000001",
        occurred_at: NOW,
        action: "auth.login.success",
        outcome: "success",
        actor_label: "admin",
        target_type: "session",
        target_id: null,
      },
    ],
    activity_scope: "all",
  };
}

export function providerList(): ProviderList {
  return {
    items: [
      {
        id: "shodan",
        name: "Shodan",
        category: "internet_assets",
        category_label: "Internet asset intelligence",
        access: "freemium",
        access_label: "Limited free tier",
        auth: "api_key",
        docs_url: "https://developer.shodan.io/api",
        phase: 5,
        status: "planned",
        status_message: "Planned — integration not yet implemented.",
        modules: ["ip"],
        notes: "Free accounts have little quota.",
      },
      {
        id: "cisco_talos",
        name: "Cisco Talos",
        category: "threat",
        category_label: "Threat intelligence",
        access: "none",
        access_label: "No official API",
        auth: "none",
        docs_url: "https://talosintelligence.com/",
        phase: 6,
        status: "excluded",
        status_message: "Excluded — see notes.",
        modules: ["threat"],
        notes: "No official public API.",
      },
    ],
    counts: { total: 2, available: 0, planned: 1, excluded: 1 },
    categories: [
      { key: "internet_assets", label: "Internet asset intelligence", count: 1 },
      { key: "threat", label: "Threat intelligence", count: 1 },
    ],
  };
}

/** Handlers every signed-in page needs. */
export function shellHandlers(state: AuthState = authState()) {
  return {
    "GET /auth/me": { body: state },
    "GET /system/info": { body: { service: "omniosint", version: "0.1.0", api_version: "v1", setup_required: false } },
    "GET /system/features": { body: featureList() },
    "GET /system/health/live": { body: { status: "ok" } },
    "GET /system/health/ready": { body: readiness() },
  } as const;
}
