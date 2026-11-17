import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router";

import { ApiError } from "@/api/client";
import { useCompleteSetup, useLogin, useSetupStatus, useSystemInfo } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { FormError, Notice } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/surface";

import { AuthLayout } from "./AuthLayout";
import { passwordGuidance } from "./passwords";

/**
 * The one-time setup token from the URL fragment (#token=...). Browsers never
 * send the fragment to the server, so the token stays out of request logs.
 */
function readTokenFromFragment(): string {
  const match = /(?:^#|&)token=([^&]+)/.exec(window.location.hash);
  if (!match?.[1]) return "";
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return "";
  }
}

/** Removes the token from the address bar once it has been read. */
function clearFragment(): void {
  if (window.location.hash) {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
}

export function SetupPage() {
  const navigate = useNavigate();
  const info = useSystemInfo();
  const status = useSetupStatus(info.data?.setup_required === true);
  const setup = useCompleteSetup();
  const login = useLogin();

  const [token, setToken] = useState(readTokenFromFragment);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mismatch, setMismatch] = useState(false);

  useEffect(clearFragment, []);

  if (info.isPending) {
    return (
      <AuthLayout title="First-run setup">
        <Skeleton className="h-40" />
      </AuthLayout>
    );
  }
  if (info.data && !info.data.setup_required) return <Navigate to="/login" replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    try {
      await setup.mutateAsync({
        setup_token: token.trim(),
        username,
        display_name: displayName,
        email: email.trim() || null,
        password,
      });
    } catch {
      return;
    }
    try {
      await login.mutateAsync({ username, password });
      navigate("/", { replace: true });
    } catch {
      navigate("/login", {
        replace: true,
        state: { notice: "The administrator account was created. Sign in to continue." },
      });
    }
  }

  const error = setup.error instanceof ApiError ? setup.error : null;
  const fieldErrors = (field: string) => error?.fieldErrors(field) ?? [];

  return (
    <AuthLayout
      wide
      title="First-run setup"
      description="Create the first administrator account. This page works only once, while no account exists."
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <Notice title="Setup token">
          {token ? (
            "The setup token was filled in from the link you opened."
          ) : (
            <>
              Copy the token from the file below, or run <code>omniosint admin setup-token</code> on
              this computer.
              {status.data?.token_file ? (
                <code className="mt-1 block break-all text-xs text-fg">{status.data.token_file}</code>
              ) : null}
            </>
          )}
        </Notice>
        <FormError
          error={setup.error}
          fields={["setup_token", "username", "display_name", "email", "password"]}
        />
        <Field label="Setup token" errors={fieldErrors("setup_token")}>
          {(props) => (
            <Input
              {...props}
              name="setup_token"
              autoComplete="off"
              spellCheck={false}
              className="font-mono"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              required
            />
          )}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Username" errors={fieldErrors("username")} hint="Lower-case letters, digits, . _ -">
            {(props) => (
              <Input
                {...props}
                name="username"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            )}
          </Field>
          <Field label="Display name" optional errors={fieldErrors("display_name")}>
            {(props) => (
              <Input
                {...props}
                name="display_name"
                autoComplete="name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
              />
            )}
          </Field>
        </div>
        <Field label="Email" optional errors={fieldErrors("email")}>
          {(props) => (
            <Input
              {...props}
              name="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          )}
        </Field>
        <Field label="Password" errors={fieldErrors("password")} hint={passwordGuidance}>
          {(props) => (
            <Input
              {...props}
              name="password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          )}
        </Field>
        <Field label="Confirm password" errors={mismatch ? ["The passwords do not match."] : []}>
          {(props) => (
            <Input
              {...props}
              name="confirm"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              required
            />
          )}
        </Field>
        <Button
          type="submit"
          variant="primary"
          className="w-full"
          loading={setup.isPending || login.isPending}
          disabled={!token || !username || !password || !confirm}
        >
          Create administrator
        </Button>
      </form>
    </AuthLayout>
  );
}
