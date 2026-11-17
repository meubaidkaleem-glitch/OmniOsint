import { WifiOff } from "lucide-react";
import { useMemo } from "react";
import { Outlet } from "react-router";

import { useFeatures, useLiveness } from "@/api/queries";
import type { AuthState, FeatureOut } from "@/api/types";

import { CommandPalette } from "./CommandPalette";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

function BackendBanner() {
  const { isError, failureCount } = useLiveness();
  if (!isError) return null;
  return (
    <div
      role="alert"
      className="flex items-center gap-2 border-b border-danger/40 bg-danger-soft px-4 py-2 text-sm text-fg"
    >
      <WifiOff className="size-4 text-danger" aria-hidden />
      <span>
        The OmniOSINT service is not responding. It may have been stopped. Retrying automatically
        {failureCount > 1 ? ` (${failureCount} attempts)` : ""}.
      </span>
    </div>
  );
}

export function AppShell({ me }: { me: AuthState }) {
  const featuresQuery = useFeatures();
  const features = useMemo(
    () => new Map<string, FeatureOut>((featuresQuery.data?.features ?? []).map((f) => [f.key, f])),
    [featuresQuery.data],
  );

  return (
    <div className="flex h-full overflow-hidden">
      <Sidebar features={features} permissions={me.permissions} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar me={me} />
        <BackendBanner />
        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1400px] px-6 py-6">
            <Outlet context={{ me, features, featuresLoading: featuresQuery.isPending }} />
          </div>
        </main>
      </div>
      <CommandPalette features={features} permissions={me.permissions} />
    </div>
  );
}
