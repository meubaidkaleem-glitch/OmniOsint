import { Moon, Sun } from "lucide-react";
import { useState } from "react";

import { useShell } from "@/app/context";
import { useRevokeSession, useSessions } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { ErrorState, Notice } from "@/components/ui/feedback";
import { Badge, DefinitionList, Panel, Skeleton } from "@/components/ui/surface";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatDateTime, formatRelative } from "@/lib/format";
import { ChangePasswordForm } from "@/pages/auth/ChangePasswordForm";
import { useUiStore } from "@/stores/ui";

function SessionsPanel() {
  const sessions = useSessions();
  const revoke = useRevokeSession();
  return (
    <Panel title="Active sessions" description="Places where you are signed in." bodyClassName="p-0">
      {sessions.isPending ? (
        <div className="p-4">
          <Skeleton className="h-16" />
        </div>
      ) : sessions.isError ? (
        <div className="p-4">
          <ErrorState error={sessions.error} onRetry={() => void sessions.refetch()} />
        </div>
      ) : (
        <Table>
          <THead>
            <tr>
              <TH>Client</TH>
              <TH>Address</TH>
              <TH>Signed in</TH>
              <TH>Last used</TH>
              <TH>Expires</TH>
              <TH />
            </tr>
          </THead>
          <TBody>
            {sessions.data.items.map((session) => (
              <TR key={session.id}>
                <TD>
                  <div className="flex items-center gap-2 text-fg">
                    <span className="capitalize">{session.client_type}</span>
                    {session.current ? <Badge tone="accent">This session</Badge> : null}
                  </div>
                  <div className="max-w-xs truncate text-xs text-fg-subtle" title={session.user_agent ?? undefined}>
                    {session.user_agent ?? "Unknown client"}
                  </div>
                </TD>
                <TD className="font-mono text-xs text-fg-muted">{session.ip_address ?? "—"}</TD>
                <TD className="whitespace-nowrap text-fg-muted">{formatDateTime(session.created_at)}</TD>
                <TD className="whitespace-nowrap text-fg-muted">{formatRelative(session.last_seen_at)}</TD>
                <TD className="whitespace-nowrap text-fg-muted">{formatDateTime(session.expires_at)}</TD>
                <TD className="text-right">
                  {!session.current ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={revoke.isPending && revoke.variables === session.id}
                      onClick={() => revoke.mutate(session.id)}
                    >
                      End session
                    </Button>
                  ) : null}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </Panel>
  );
}

export function AccountPage() {
  const { me } = useShell();
  const { theme, setTheme } = useUiStore();
  const [changed, setChanged] = useState<number | null>(null);
  const user = me.user;

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Profile">
        <DefinitionList
          items={[
            ["Username", <code key="u">{user.username}</code>],
            ["Display name", user.display_name],
            ["Email", user.email ?? "—"],
            ["Roles", user.roles.join(", ")],
            ["Last sign-in", formatDateTime(user.last_login_at)],
            ["Password changed", formatDateTime(user.password_changed_at)],
          ]}
        />
        <div className="mt-4 text-xs uppercase tracking-wider text-fg-subtle">Permissions</div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {me.permissions.length ? (
            me.permissions.map((permission) => (
              <Badge key={permission}>
                <code>{permission}</code>
              </Badge>
            ))
          ) : (
            <span className="text-sm text-fg-subtle">None yet.</span>
          )}
        </div>
      </Panel>

      <Panel title="Change password" description="Your other sessions end when you change it.">
        {changed !== null ? (
          <Notice className="mb-4" title="Password changed">
            {changed === 0 ? "No other session was active." : `${changed} other session(s) ended.`}
          </Notice>
        ) : null}
        <ChangePasswordForm onChanged={setChanged} />
      </Panel>

      <Panel title="Appearance" description="Stored in this browser only.">
        <div className="flex gap-2" role="radiogroup" aria-label="Theme">
          {(["dark", "light"] as const).map((option) => (
            <Button
              key={option}
              role="radio"
              aria-checked={theme === option}
              variant={theme === option ? "primary" : "secondary"}
              icon={option === "dark" ? <Moon className="size-4" /> : <Sun className="size-4" />}
              onClick={() => setTheme(option)}
            >
              {option === "dark" ? "Dark" : "Light"}
            </Button>
          ))}
        </div>
      </Panel>

      <div className="xl:col-span-2">
        <SessionsPanel />
      </div>
    </div>
  );
}
