import { KeyRound, MoreHorizontal, Pencil, Plus, Power, Trash2, Unlock } from "lucide-react";
import { useDeferredValue, useState } from "react";

import { useCan, useShell } from "@/app/context";
import { useDeleteUser, useUnlockUser, useUpdateUser, useUsers } from "@/api/queries";
import type { UserOut } from "@/api/types";
import { Button, IconButton } from "@/components/ui/button";
import { EmptyState, ErrorState, Notice } from "@/components/ui/feedback";
import { Input } from "@/components/ui/form";
import { Dialog, MenuContent, MenuItem, MenuRoot, MenuSeparator, MenuTrigger } from "@/components/ui/overlay";
import { Badge, Panel, Skeleton } from "@/components/ui/surface";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatRelative } from "@/lib/format";
import { NoAccessPage } from "@/pages/MiscPages";

import { CreateUserDialog, EditUserDialog, ResetPasswordDialog } from "./UserDialogs";

function isLocked(user: UserOut): boolean {
  return user.locked_until !== null && new Date(user.locked_until).getTime() > Date.now();
}

function UserStatus({ user }: { user: UserOut }) {
  if (!user.is_active) return <Badge>Inactive</Badge>;
  if (isLocked(user)) return <Badge tone="danger">Locked</Badge>;
  if (user.must_change_password) return <Badge tone="warn">Password change due</Badge>;
  return <Badge tone="ok">Active</Badge>;
}

type Action =
  | { kind: "edit" | "reset" | "delete" | "toggle"; user: UserOut }
  | null;

export function UsersPage() {
  const can = useCan();
  const { me } = useShell();
  const [search, setSearch] = useState("");
  const deferred = useDeferredValue(search.trim());
  const users = useUsers(deferred);
  const [creating, setCreating] = useState(false);
  const [action, setAction] = useState<Action>(null);
  const unlock = useUnlockUser();
  const update = useUpdateUser();
  const remove = useDeleteUser();

  if (!can("users:read")) return <NoAccessPage permission="users:read" />;
  const canManage = can("users:manage");
  const rows = users.data?.pages.flatMap((page) => page.items) ?? [];
  const total = users.data?.pages[0]?.total ?? 0;

  return (
    <>
      <Panel
        title="Users"
        description={users.data ? `${total} account${total === 1 ? "" : "s"}` : undefined}
        bodyClassName="p-0"
        actions={
          <>
            <Input
              aria-label="Search users"
              placeholder="Search name, username or email"
              className="h-8 w-64"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            {canManage ? (
              <Button variant="primary" size="sm" icon={<Plus className="size-3.5" />} onClick={() => setCreating(true)}>
                New user
              </Button>
            ) : null}
          </>
        }
      >
        {users.isPending ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton key={index} className="h-8" />
            ))}
          </div>
        ) : users.isError ? (
          <div className="p-4">
            <ErrorState error={users.error} onRetry={() => void users.refetch()} />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState title={deferred ? "No user matches this search." : "No users."} />
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>User</TH>
                <TH>Roles</TH>
                <TH>Status</TH>
                <TH>Last sign-in</TH>
                <TH className="w-10" />
              </tr>
            </THead>
            <TBody>
              {rows.map((user) => (
                <TR key={user.id}>
                  <TD>
                    <div className="font-medium text-fg">
                      {user.display_name}
                      {user.id === me.user.id ? <span className="ml-2 text-xs text-fg-subtle">(you)</span> : null}
                    </div>
                    <div className="font-mono text-xs text-fg-subtle">
                      {user.username}
                      {user.email ? <span className="ml-2 font-sans">{user.email}</span> : null}
                    </div>
                  </TD>
                  <TD>
                    <div className="flex flex-wrap gap-1">
                      {user.roles.map((role) => (
                        <Badge key={role} tone={role === "administrator" ? "accent" : "neutral"} className="capitalize">
                          {role}
                        </Badge>
                      ))}
                    </div>
                  </TD>
                  <TD>
                    <UserStatus user={user} />
                  </TD>
                  <TD className="whitespace-nowrap text-fg-muted">{formatRelative(user.last_login_at)}</TD>
                  <TD>
                    {canManage ? (
                      <MenuRoot>
                        <MenuTrigger asChild>
                          <IconButton label={`Actions for ${user.username}`}>
                            <MoreHorizontal className="size-4" />
                          </IconButton>
                        </MenuTrigger>
                        <MenuContent>
                          <MenuItem icon={<Pencil className="size-4" />} onSelect={() => setAction({ kind: "edit", user })}>
                            Edit
                          </MenuItem>
                          <MenuItem icon={<KeyRound className="size-4" />} onSelect={() => setAction({ kind: "reset", user })}>
                            Reset password
                          </MenuItem>
                          {isLocked(user) ? (
                            <MenuItem icon={<Unlock className="size-4" />} onSelect={() => unlock.mutate(user.id)}>
                              Clear lockout
                            </MenuItem>
                          ) : null}
                          <MenuItem icon={<Power className="size-4" />} onSelect={() => setAction({ kind: "toggle", user })}>
                            {user.is_active ? "Deactivate" : "Activate"}
                          </MenuItem>
                          <MenuSeparator />
                          <MenuItem
                            danger
                            disabled={user.id === me.user.id}
                            icon={<Trash2 className="size-4" />}
                            onSelect={() => setAction({ kind: "delete", user })}
                          >
                            Delete
                          </MenuItem>
                        </MenuContent>
                      </MenuRoot>
                    ) : null}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
        {users.hasNextPage ? (
          <div className="border-t border-line p-3 text-center">
            <Button size="sm" onClick={() => void users.fetchNextPage()} loading={users.isFetchingNextPage}>
              Load more
            </Button>
          </div>
        ) : null}
      </Panel>

      {unlock.isError || update.isError ? (
        <Notice tone="danger" className="mt-4" title={((unlock.error ?? update.error) as Error).message} />
      ) : null}

      <CreateUserDialog open={creating} onOpenChange={setCreating} />
      {action?.kind === "edit" ? <EditUserDialog user={action.user} onClose={() => setAction(null)} /> : null}
      {action?.kind === "reset" ? <ResetPasswordDialog user={action.user} onClose={() => setAction(null)} /> : null}
      {action?.kind === "toggle" || action?.kind === "delete" ? (
        <ConfirmDialog
          title={
            action.kind === "delete"
              ? `Delete ${action.user.username}?`
              : `${action.user.is_active ? "Deactivate" : "Activate"} ${action.user.username}?`
          }
          description={
            action.kind === "delete"
              ? "The account can no longer sign in and its sessions end. The username stays reserved so the audit trail remains unambiguous."
              : action.user.is_active
                ? "The user's sessions end and they cannot sign in until the account is activated again."
                : "The user can sign in again."
          }
          confirmLabel={action.kind === "delete" ? "Delete user" : action.user.is_active ? "Deactivate" : "Activate"}
          danger={action.kind === "delete" || action.user.is_active}
          error={action.kind === "delete" ? remove.error : update.error}
          pending={remove.isPending || update.isPending}
          onCancel={() => {
            remove.reset();
            update.reset();
            setAction(null);
          }}
          onConfirm={async () => {
            try {
              if (action.kind === "delete") await remove.mutateAsync(action.user.id);
              else await update.mutateAsync({ id: action.user.id, changes: { is_active: !action.user.is_active } });
              setAction(null);
            } catch {
              // Shown in the dialog.
            }
          }}
        />
      ) : null}
    </>
  );
}

function ConfirmDialog({
  title,
  description,
  confirmLabel,
  danger,
  error,
  pending,
  onCancel,
  onConfirm,
}: {
  title: string;
  description: string;
  confirmLabel: string;
  danger: boolean;
  error: unknown;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onCancel()}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} loading={pending} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {error ? <Notice tone="danger" title={(error as Error).message} /> : <p className="text-sm text-fg-muted">This is recorded in the audit log.</p>}
    </Dialog>
  );
}
