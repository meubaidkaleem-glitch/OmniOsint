import { useCan } from "@/app/context";
import { useRoles } from "@/api/queries";
import { ErrorState } from "@/components/ui/feedback";
import { Badge, Panel, Skeleton } from "@/components/ui/surface";
import { NoAccessPage } from "@/pages/MiscPages";

export function RolesPage() {
  const can = useCan();
  const roles = useRoles();
  if (!can("roles:read")) return <NoAccessPage permission="roles:read" />;
  if (roles.isPending) return <Skeleton className="h-64" />;
  if (roles.isError) return <ErrorState error={roles.error} onRetry={() => void roles.refetch()} />;

  return (
    <div className="space-y-4">
      <p className="text-sm text-fg-muted">
        Built-in roles are defined by OmniOSINT and updated with each version. Permissions for
        investigation work are added to the analyst role as intelligence modules are built.
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        {roles.data.items.map((role) => (
          <Panel
            key={role.id}
            title={<span className="capitalize">{role.name}</span>}
            description={role.description}
            actions={
              <>
                {role.is_system ? <Badge>Built-in</Badge> : null}
                <Badge tone="accent">
                  {role.member_count} member{role.member_count === 1 ? "" : "s"}
                </Badge>
              </>
            }
          >
            {role.permissions.length === 0 ? (
              <p className="text-sm text-fg-subtle">No permissions yet.</p>
            ) : (
              <ul className="space-y-1.5">
                {role.permissions.map((permission) => (
                  <li key={permission.code} className="flex gap-3 text-sm">
                    <code className="w-32 shrink-0 text-xs text-accent">{permission.code}</code>
                    <span className="text-fg-muted">{permission.description}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        ))}
      </div>
    </div>
  );
}
