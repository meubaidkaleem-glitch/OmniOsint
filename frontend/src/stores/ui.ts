/** Per-browser interface preferences. Nothing here is sent to the server. */
import { create } from "zustand";

export type Theme = "dark" | "light";

const THEME_KEY = "omniosint.theme";
const SIDEBAR_KEY = "omniosint.sidebar.collapsed";
const GROUPS_KEY = "omniosint.sidebar.closedGroups";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable (private mode, policy); preferences then last
    // for the session only.
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

export function initialTheme(): Theme {
  return read(THEME_KEY) === "light" ? "light" : "dark";
}

function initialClosedGroups(): string[] {
  try {
    const parsed: unknown = JSON.parse(read(GROUPS_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : [];
  } catch {
    return [];
  }
}

interface UiState {
  theme: Theme;
  sidebarCollapsed: boolean;
  closedGroups: string[];
  paletteOpen: boolean;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  toggleSidebar: () => void;
  toggleGroup: (group: string) => void;
  setPaletteOpen: (open: boolean) => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  theme: initialTheme(),
  sidebarCollapsed: read(SIDEBAR_KEY) === "1",
  closedGroups: initialClosedGroups(),
  paletteOpen: false,
  setTheme: (theme) => {
    write(THEME_KEY, theme);
    applyTheme(theme);
    set({ theme });
  },
  toggleTheme: () => get().setTheme(get().theme === "dark" ? "light" : "dark"),
  toggleSidebar: () => {
    const collapsed = !get().sidebarCollapsed;
    write(SIDEBAR_KEY, collapsed ? "1" : "0");
    set({ sidebarCollapsed: collapsed });
  },
  toggleGroup: (group) => {
    const current = get().closedGroups;
    const next = current.includes(group)
      ? current.filter((item) => item !== group)
      : [...current, group];
    write(GROUPS_KEY, JSON.stringify(next));
    set({ closedGroups: next });
  },
  setPaletteOpen: (open) => set({ paletteOpen: open }),
}));
