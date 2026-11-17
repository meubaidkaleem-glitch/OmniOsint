import { useOutletContext } from "react-router";

import type { AuthState, FeatureOut } from "@/api/types";

export interface ShellContext {
  me: AuthState;
  features: Map<string, FeatureOut>;
  featuresLoading: boolean;
}

/** Data the application shell shares with every page inside it. */
export function useShell(): ShellContext {
  return useOutletContext<ShellContext>();
}

export function useCan(): (permission: string) => boolean {
  const { me } = useShell();
  return (permission) => me.permissions.includes(permission);
}
