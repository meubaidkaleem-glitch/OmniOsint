import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from "react";
import { forwardRef, useId } from "react";

import { cn } from "@/lib/format";

const CONTROL =
  "rounded-md border border-line-strong bg-surface-2 px-3 text-sm text-fg " +
  "placeholder:text-fg-subtle transition-colors focus:border-accent focus:outline-none " +
  "aria-[invalid=true]:border-danger disabled:opacity-60";

/**
 * Default width and height that a caller's own w-* or h-* classes replace.
 * (Two conflicting utilities would otherwise be decided by stylesheet order.)
 */
function controlClasses(className: string | undefined, extra = ""): string {
  const own = className ?? "";
  return cn(
    CONTROL,
    /(^|\s)(w-|min-w-|flex-)/.test(own) ? null : "w-full",
    /(^|\s)h-/.test(own) ? null : "h-9",
    extra,
    own,
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return <input ref={ref} className={controlClasses(className)} {...rest} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...rest }, ref) {
    return (
      <select ref={ref} className={controlClasses(className, "pr-8")} {...rest}>
        {children}
      </select>
    );
  },
);

export function Checkbox({
  label,
  description,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode; description?: ReactNode }) {
  const id = useId();
  return (
    <label htmlFor={rest.id ?? id} className="flex cursor-pointer items-start gap-2.5 text-sm">
      <input
        id={rest.id ?? id}
        type="checkbox"
        className="mt-0.5 size-4 shrink-0 accent-[var(--c-accent-strong)]"
        {...rest}
      />
      <span>
        <span className="text-fg">{label}</span>
        {description ? <span className="block text-xs text-fg-muted">{description}</span> : null}
      </span>
    </label>
  );
}

export interface FieldProps {
  label: ReactNode;
  hint?: ReactNode;
  errors?: string[];
  optional?: boolean;
  children: (props: { id: string; "aria-invalid"?: boolean; "aria-describedby"?: string }) => ReactNode;
}

/** A labelled control with optional hint and field errors from the API. */
export function Field({ label, hint, errors = [], optional, children }: FieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, errors.length ? errorId : null]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="flex items-baseline justify-between text-xs font-medium text-fg-muted">
        <span>{label}</span>
        {optional ? <span className="font-normal text-fg-subtle">Optional</span> : null}
      </label>
      {children({
        id,
        "aria-invalid": errors.length ? true : undefined,
        "aria-describedby": describedBy || undefined,
      })}
      {hint ? (
        <p id={hintId} className="text-xs text-fg-subtle">
          {hint}
        </p>
      ) : null}
      {errors.length ? (
        <ul id={errorId} className="space-y-0.5 text-xs text-danger" role="alert">
          {errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
