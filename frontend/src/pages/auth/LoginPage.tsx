import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { ApiError } from "@/api/client";
import { useLogin, useMe, useSystemInfo } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form";

import { AuthLayout } from "./AuthLayout";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const me = useMe();
  const info = useSystemInfo();
  const login = useLogin();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const notice = (location.state as { notice?: string } | null)?.notice;

  if (info.data?.setup_required) return <Navigate to="/setup" replace />;
  if (me.data) return <Navigate to={from} replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      const result = await login.mutateAsync({ username, password });
      navigate(result.user.must_change_password ? "/change-password" : from, { replace: true });
    } catch {
      setPassword("");
    }
  }

  const error = login.error instanceof ApiError ? login.error : login.error ? login.error : null;

  return (
    <AuthLayout title="Sign in" description="Use your OmniOSINT account.">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {notice ? (
          <p className="rounded-md border border-ok/30 bg-ok-soft px-3 py-2 text-sm text-fg">{notice}</p>
        ) : null}
        <FormError error={error} fields={["username", "password"]} />
        <Field label="Username">
          {(props) => (
            <Input
              {...props}
              name="username"
              autoComplete="username"
              autoFocus
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          )}
        </Field>
        <Field label="Password">
          {(props) => (
            <Input
              {...props}
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          )}
        </Field>
        <Button
          type="submit"
          variant="primary"
          className="w-full"
          loading={login.isPending}
          disabled={!username || !password}
        >
          Sign in
        </Button>
        {info.isError ? (
          <p className="text-xs text-danger">The OmniOSINT service is not reachable.</p>
        ) : null}
      </form>
    </AuthLayout>
  );
}
