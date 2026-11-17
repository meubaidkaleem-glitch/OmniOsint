import { Navigate, useLocation } from "react-router";

import { useMe, useSystemInfo } from "@/api/queries";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorState } from "@/components/ui/feedback";
import { Skeleton } from "@/components/ui/surface";

function FullPageLoading() {
  return (
    <div className="flex h-full items-center justify-center" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-2 w-48" />
    </div>
  );
}

/**
 * Gate for every page inside the application shell:
 * first-run setup -> sign-in -> required password change -> page.
 */
export function RequireAuth() {
  const location = useLocation();
  const me = useMe();
  const info = useSystemInfo();

  if (me.isPending) return <FullPageLoading />;
  if (me.isError) {
    return (
      <div className="mx-auto max-w-xl p-8">
        <ErrorState error={me.error} onRetry={() => void me.refetch()} />
      </div>
    );
  }
  if (me.data === null) {
    if (info.isPending) return <FullPageLoading />;
    if (info.data?.setup_required) return <Navigate to="/setup" replace />;
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  if (me.data.user.must_change_password) return <Navigate to="/change-password" replace />;
  return <AppShell me={me.data} />;
}
