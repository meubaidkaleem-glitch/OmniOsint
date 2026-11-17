import { useState, type FormEvent } from "react";

import { ApiError } from "@/api/client";
import { useChangePassword } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form";

import { passwordGuidance } from "./passwords";

export function ChangePasswordForm({ onChanged }: { onChanged: (otherSessionsEnded: number) => void }) {
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mismatch, setMismatch] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (next !== confirm) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    try {
      const result = await change.mutateAsync({ current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setConfirm("");
      onChanged(result.other_sessions_ended);
    } catch {
      // Shown through change.error.
    }
  }

  const error = change.error instanceof ApiError ? change.error : null;
  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <FormError error={change.error} fields={["current_password", "new_password"]} />
      <Field label="Current password" errors={error?.fieldErrors("current_password") ?? []}>
        {(props) => (
          <Input
            {...props}
            name="current_password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
        )}
      </Field>
      <Field label="New password" hint={passwordGuidance} errors={error?.fieldErrors("new_password") ?? []}>
        {(props) => (
          <Input
            {...props}
            name="new_password"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
        )}
      </Field>
      <Field label="Confirm new password" errors={mismatch ? ["The passwords do not match."] : []}>
        {(props) => (
          <Input
            {...props}
            name="confirm_password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
          />
        )}
      </Field>
      <Button
        type="submit"
        variant="primary"
        loading={change.isPending}
        disabled={!current || !next || !confirm}
      >
        Change password
      </Button>
    </form>
  );
}
