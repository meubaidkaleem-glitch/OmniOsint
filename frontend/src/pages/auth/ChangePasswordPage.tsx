import { Navigate, useNavigate } from "react-router";

import { useLogout, useMe } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/surface";

import { AuthLayout } from "./AuthLayout";
import { ChangePasswordForm } from "./ChangePasswordForm";

/** Shown when an administrator has required a new password. */
export function ChangePasswordPage() {
  const navigate = useNavigate();
  const me = useMe();
  const logout = useLogout();

  if (me.isPending) {
    return (
      <AuthLayout title="Change your password">
        <Skeleton className="h-40" />
      </AuthLayout>
    );
  }
  if (!me.data) return <Navigate to="/login" replace />;
  if (!me.data.user.must_change_password) return <Navigate to="/" replace />;

  return (
    <AuthLayout
      title="Change your password"
      description="An administrator set a temporary password for this account. Choose a new one to continue."
    >
      <ChangePasswordForm onChanged={() => navigate("/", { replace: true })} />
      <Button
        variant="ghost"
        size="sm"
        className="mt-3"
        onClick={() => logout.mutate(undefined, { onSettled: () => navigate("/login") })}
      >
        Sign out instead
      </Button>
    </AuthLayout>
  );
}
