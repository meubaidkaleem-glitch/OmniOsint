import type { ReactNode } from "react";

export function AuthLayout({
  title,
  description,
  children,
  wide = false,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className="flex min-h-full items-start justify-center overflow-y-auto px-4 py-[8vh]">
      <div className={wide ? "w-full max-w-lg" : "w-full max-w-sm"}>
        <div className="mb-6 flex items-center gap-3">
          <img src="/favicon.svg" alt="" className="size-9" />
          <div>
            <div className="text-lg font-semibold tracking-tight text-fg">OmniOSINT</div>
            <div className="text-xs text-fg-subtle">Evidence-driven intelligence platform</div>
          </div>
        </div>
        <div className="rounded-lg border border-line bg-surface p-6">
          <h1 className="text-base font-semibold text-fg">{title}</h1>
          {description ? <div className="mt-1 text-sm text-fg-muted">{description}</div> : null}
          <div className="mt-5">{children}</div>
        </div>
        <p className="mt-4 text-center text-xs text-fg-subtle">
          Local interface · available on this computer only
        </p>
      </div>
    </div>
  );
}
