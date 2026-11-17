import { useState, type FormEvent } from "react";

import { ApiError } from "@/api/client";
import { useCreateUser, useResetPassword, useRoles, useUpdateUser } from "@/api/queries";
import type { RoleOut, UserOut } from "@/api/types";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/feedback";
import { Checkbox, Field, Input } from "@/components/ui/form";
import { Dialog } from "@/components/ui/overlay";
import { passwordGuidance } from "@/pages/auth/passwords";

function RolePicker({
  roles,
  selected,
  onChange,
  errors,
}: {
  roles: RoleOut[];
  selected: string[];
  onChange: (roles: string[]) => void;
  errors: string[];
}) {
  return (
    <fieldset className="space-y-2">
      <legend className="mb-1 text-xs font-medium text-fg-muted">Roles</legend>
      {roles.map((role) => (
        <Checkbox
          key={role.name}
          name="roles"
          value={role.name}
          checked={selected.includes(role.name)}
          onChange={(event) =>
            onChange(
              event.target.checked
                ? [...selected, role.name]
                : selected.filter((name) => name !== role.name),
            )
          }
          label={<span className="capitalize">{role.name}</span>}
          description={role.description}
        />
      ))}
      {errors.length ? (
        <ul className="text-xs text-danger" role="alert">
          {errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      ) : null}
    </fieldset>
  );
}

function fieldErrors(error: unknown, field: string): string[] {
  return error instanceof ApiError ? error.fieldErrors(field) : [];
}

export function CreateUserDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const roles = useRoles();
  const create = useCreateUser();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [selected, setSelected] = useState<string[]>(["analyst"]);
  const [mustChange, setMustChange] = useState(true);

  function reset() {
    setUsername("");
    setDisplayName("");
    setEmail("");
    setPassword("");
    setSelected(["analyst"]);
    setMustChange(true);
    create.reset();
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      await create.mutateAsync({
        username,
        display_name: displayName,
        email: email.trim() || null,
        password,
        roles: selected,
        must_change_password: mustChange,
      });
      reset();
      onOpenChange(false);
    } catch {
      // Shown below.
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
      title="New user"
      description="The user signs in with this username and the initial password."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form="create-user" variant="primary" loading={create.isPending}>
            Create user
          </Button>
        </>
      }
    >
      <form id="create-user" onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormError error={create.error} fields={["username", "display_name", "email", "password", "roles"]} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Username" errors={fieldErrors(create.error, "username")}>
            {(props) => (
              <Input {...props} name="username" autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} />
            )}
          </Field>
          <Field label="Display name" optional errors={fieldErrors(create.error, "display_name")}>
            {(props) => (
              <Input {...props} name="display_name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            )}
          </Field>
        </div>
        <Field label="Email" optional errors={fieldErrors(create.error, "email")}>
          {(props) => (
            <Input {...props} name="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          )}
        </Field>
        <Field label="Initial password" hint={passwordGuidance} errors={fieldErrors(create.error, "password")}>
          {(props) => (
            <Input
              {...props}
              name="password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
        </Field>
        <RolePicker
          roles={roles.data?.items ?? []}
          selected={selected}
          onChange={setSelected}
          errors={fieldErrors(create.error, "roles")}
        />
        <Checkbox
          name="must_change_password"
          checked={mustChange}
          onChange={(event) => setMustChange(event.target.checked)}
          label="Require a new password at first sign-in"
        />
      </form>
    </Dialog>
  );
}

export function EditUserDialog({ user, onClose }: { user: UserOut; onClose: () => void }) {
  const roles = useRoles();
  const update = useUpdateUser();
  const [displayName, setDisplayName] = useState(user.display_name);
  const [email, setEmail] = useState(user.email ?? "");
  const [selected, setSelected] = useState<string[]>(user.roles);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      await update.mutateAsync({
        id: user.id,
        changes: { display_name: displayName, email: email.trim() || null, roles: selected },
      });
      onClose();
    } catch {
      // Shown below.
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={`Edit ${user.username}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="edit-user" variant="primary" loading={update.isPending}>
            Save changes
          </Button>
        </>
      }
    >
      <form id="edit-user" onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormError error={update.error} fields={["display_name", "email", "roles"]} />
        <Field label="Display name" errors={fieldErrors(update.error, "display_name")}>
          {(props) => <Input {...props} name="display_name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />}
        </Field>
        <Field label="Email" optional errors={fieldErrors(update.error, "email")}>
          {(props) => <Input {...props} name="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />}
        </Field>
        <RolePicker
          roles={roles.data?.items ?? []}
          selected={selected}
          onChange={setSelected}
          errors={fieldErrors(update.error, "roles")}
        />
      </form>
    </Dialog>
  );
}

export function ResetPasswordDialog({ user, onClose }: { user: UserOut; onClose: () => void }) {
  const reset = useResetPassword();
  const [password, setPassword] = useState("");
  const [mustChange, setMustChange] = useState(true);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      await reset.mutateAsync({
        id: user.id,
        payload: { new_password: password, must_change_password: mustChange },
      });
      onClose();
    } catch {
      // Shown below.
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={`Reset password for ${user.username}`}
      description="All of the user's sessions end, and any sign-in lockout is cleared."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="reset-password" variant="primary" loading={reset.isPending}>
            Set password
          </Button>
        </>
      }
    >
      <form id="reset-password" onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormError error={reset.error} fields={["new_password"]} />
        <Field label="New password" hint={passwordGuidance} errors={fieldErrors(reset.error, "new_password")}>
          {(props) => (
            <Input
              {...props}
              name="new_password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
        </Field>
        <Checkbox
          name="must_change_password"
          checked={mustChange}
          onChange={(event) => setMustChange(event.target.checked)}
          label="Require a new password at next sign-in"
        />
      </form>
    </Dialog>
  );
}
