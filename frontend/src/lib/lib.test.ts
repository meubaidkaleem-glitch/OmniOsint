import { describe, expect, it } from "vitest";

import { useUiStore } from "@/stores/ui";

import { formatBytes, formatDuration, formatRelative, humanizeAction } from "./format";
import { ADMIN_PAGES, NAV_GROUPS, NAV_SECTIONS, canSee, sectionForPath } from "./navigation";

describe("navigation specification", () => {
  it("has the twenty sections of the brief, each once", () => {
    expect(NAV_SECTIONS).toHaveLength(20);
    expect(new Set(NAV_SECTIONS.map((section) => section.key)).size).toBe(20);
    expect(new Set(NAV_SECTIONS.map((section) => section.path)).size).toBe(20);
    expect(NAV_SECTIONS[0]?.title).toBe("Dashboard");
    expect(NAV_SECTIONS.at(-1)?.title).toBe("Administration and Settings");
    for (const section of NAV_SECTIONS) {
      expect(section.group === null || NAV_GROUPS.includes(section.group)).toBe(true);
    }
  });

  it("filters administration pages by permission", () => {
    const visible = ADMIN_PAGES.filter((page) => canSee(page.permission, ["audit:read"]));
    expect(visible.map((page) => page.title)).toEqual(["My account", "Audit log"]);
  });

  it("finds the section for a path", () => {
    expect(sectionForPath("/")?.key).toBe("dashboard");
    expect(sectionForPath("/admin/users")?.key).toBe("administration");
    expect(sectionForPath("/graph")?.key).toBe("relationship_graph");
    expect(sectionForPath("/nowhere")).toBeUndefined();
  });
});

describe("formatting", () => {
  it("formats relative times", () => {
    const now = Date.parse("2026-11-17T12:00:00Z");
    expect(formatRelative(null, now)).toBe("never");
    expect(formatRelative("2026-11-17T11:58:00Z", now)).toBe("2 minutes ago");
    expect(formatRelative("2026-11-17T09:00:00Z", now)).toBe("3 hours ago");
    expect(formatRelative("not a date", now)).toBe("—");
  });

  it("formats durations, sizes and audit actions", () => {
    expect(formatDuration(42)).toBe("42s");
    expect(formatDuration(3_725)).toBe("1h 2m");
    expect(formatDuration(90_000)).toBe("1d 1h");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(3 * 1024 ** 3)).toBe("3.0 GiB");
    expect(humanizeAction("auth.login.failure")).toBe("Login failure");
    expect(humanizeAction("user.password.reset")).toBe("Password reset");
  });
});

describe("interface preferences", () => {
  it("toggles and remembers the theme", () => {
    useUiStore.getState().setTheme("dark");
    useUiStore.getState().toggleTheme();
    expect(useUiStore.getState().theme).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("omniosint.theme")).toBe("light");
  });

  it("remembers collapsed navigation groups", () => {
    useUiStore.getState().toggleGroup("Analysis");
    expect(useUiStore.getState().closedGroups).toContain("Analysis");
    expect(JSON.parse(window.localStorage.getItem("omniosint.sidebar.closedGroups") ?? "[]")).toEqual([
      "Analysis",
    ]);
    useUiStore.getState().toggleGroup("Analysis");
    expect(useUiStore.getState().closedGroups).not.toContain("Analysis");
  });
});
