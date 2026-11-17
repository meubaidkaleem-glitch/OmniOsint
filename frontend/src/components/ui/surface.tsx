import type { HTMLAttributes, ReactNode } from "react";

import type { HealthStatus } from "@/api/types";
import { cn } from "@/lib/format";

export function Panel({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
  ...rest
}: Omit<HTMLAttributes<HTMLElement>, "title"> & {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  bodyClassName?: string;
}) {
  return (
    <section className={cn("rounded-lg border border-line bg-surface", className)} {...rest}>
      {title || actions ? (
        <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-3">
          <div className="min-w-0">
            {title ? <h2 className="text-sm font-semibold text-fg">{title}</h2> : null}
            {description ? <p className="mt-0.5 text-xs text-fg-muted">{description}</p> : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  meta,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {meta ? <div className="mb-1 text-xs text-fg-subtle">{meta}</div> : null}
        <h1 className="text-xl font-semibold tracking-tight text-fg">{title}</h1>
        {description ? <p className="mt-1 max-w-3xl text-sm text-fg-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

type Tone = "neutral" | "accent" | "ok" | "warn" | "danger";

const TONES: Record<Tone, string> = {
  neutral: "bg-neutral-soft text-fg-muted border-line",
  accent: "bg-accent-soft text-accent border-accent/30",
  ok: "bg-ok-soft text-ok border-ok/30",
  warn: "bg-warn-soft text-warn border-warn/30",
  danger: "bg-danger-soft text-danger border-danger/30",
};

export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-medium leading-none",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

const STATUS: Record<HealthStatus, { tone: Tone; label: string; dot: string }> = {
  ok: { tone: "ok", label: "Healthy", dot: "bg-ok" },
  degraded: { tone: "warn", label: "Degraded", dot: "bg-warn" },
  unavailable: { tone: "danger", label: "Unavailable", dot: "bg-danger" },
  not_configured: { tone: "neutral", label: "Not configured", dot: "bg-fg-subtle" },
};

export function StatusDot({ status, className }: { status: HealthStatus; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2 shrink-0 rounded-full", STATUS[status].dot, className)}
    />
  );
}

export function StatusBadge({ status, label }: { status: HealthStatus; label?: string }) {
  const style = STATUS[status];
  return (
    <Badge tone={style.tone}>
      <StatusDot status={status} />
      {label ?? style.label}
    </Badge>
  );
}

export function statusLabel(status: HealthStatus): string {
  return STATUS[status].label;
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("skeleton h-4", className)} />;
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-line-strong bg-surface-3 px-1.5 py-px font-mono text-[10px] text-fg-muted">
      {children}
    </kbd>
  );
}

export function DefinitionList({ items }: { items: Array<[ReactNode, ReactNode]> }) {
  return (
    <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-6 gap-y-2 text-sm">
      {items.map(([term, value], index) => (
        <div key={index} className="contents">
          <dt className="text-fg-muted">{term}</dt>
          <dd className="min-w-0 break-words text-fg">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
