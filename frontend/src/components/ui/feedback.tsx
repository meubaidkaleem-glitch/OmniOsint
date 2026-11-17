import { AlertTriangle, Info, OctagonAlert, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { ApiError } from "@/api/client";
import { cn } from "@/lib/format";

import { Button } from "./button";

type NoticeTone = "info" | "warn" | "danger";

const NOTICE: Record<NoticeTone, { className: string; icon: ReactNode }> = {
  info: {
    className: "border-accent/30 bg-accent-soft text-fg",
    icon: <Info className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />,
  },
  warn: {
    className: "border-warn/30 bg-warn-soft text-fg",
    icon: <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />,
  },
  danger: {
    className: "border-danger/30 bg-danger-soft text-fg",
    icon: <OctagonAlert className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />,
  },
};

export function Notice({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: NoticeTone;
  title?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const style = NOTICE[tone];
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn("flex gap-2.5 rounded-md border px-3 py-2.5 text-sm", style.className, className)}
    >
      {style.icon}
      <div className="min-w-0 space-y-0.5">
        {title ? <p className="font-medium">{title}</p> : null}
        {children ? <div className="text-fg-muted">{children}</div> : null}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      <p className="text-sm font-medium text-fg">{title}</p>
      {children ? <div className="max-w-md text-sm text-fg-muted">{children}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

/** Message, request id and retry for a failed query. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const apiError = error instanceof ApiError ? error : null;
  const message = apiError?.message ?? "Something went wrong while loading this page.";
  return (
    <Notice tone="danger" title={message}>
      <div className="mt-1 flex flex-wrap items-center gap-3">
        {apiError?.hint ? <span>{apiError.hint}</span> : null}
        {apiError?.requestId ? (
          <span className="font-mono text-xs">Request ID: {apiError.requestId}</span>
        ) : null}
        {onRetry ? (
          <Button size="sm" variant="secondary" onClick={onRetry} icon={<RefreshCw className="size-3.5" />}>
            Retry
          </Button>
        ) : null}
      </div>
    </Notice>
  );
}

/** Errors that do not belong to a single form field. */
export function FormError({ error, fields = [] }: { error: unknown; fields?: string[] }) {
  if (!error) return null;
  if (!(error instanceof ApiError)) {
    return <Notice tone="danger" title="The request failed." />;
  }
  const general = error.details.filter(
    (detail) => !detail.field || !fields.includes(String(detail.field)),
  );
  const coveredByFields = error.details.length > 0 && general.length === 0;
  return (
    <Notice tone="danger" title={error.message}>
      {!coveredByFields && general.length ? (
        <ul className="list-disc pl-4">
          {general.map((detail, index) => (
            <li key={index}>{String(detail.message ?? "")}</li>
          ))}
        </ul>
      ) : null}
      {error.retryAfter ? <p>Try again in {error.retryAfter} seconds.</p> : null}
    </Notice>
  );
}
