import { CircleDashed } from "lucide-react";

import { useShell } from "@/app/context";
import type { NavSection } from "@/lib/navigation";
import { PLANNED_LABEL } from "@/lib/status";
import { Badge, PageHeader, Panel, Skeleton } from "@/components/ui/surface";

/**
 * The page for every section whose backend does not exist yet. It states the
 * plan and nothing else: no forms, sample data or controls that do nothing.
 */
export function PlannedPage({ section }: { section: NavSection }) {
  const { features, featuresLoading } = useShell();
  const feature = features.get(section.key);

  if (featuresLoading && !feature) return <Skeleton className="h-48" />;

  return (
    <>
      <PageHeader
        title={section.title}
        description={feature?.summary}
        meta={
          <Badge>
            <CircleDashed className="size-3" aria-hidden /> {PLANNED_LABEL}
          </Badge>
        }
      />
      <Panel>
        <div className="flex flex-col gap-5 md:flex-row">
          <div className="md:w-64 md:shrink-0">
            <div className="text-xs uppercase tracking-wider text-fg-subtle">Status</div>
            <p className="mt-1 text-sm font-medium text-fg">{PLANNED_LABEL}</p>
            {feature ? (
              <>
                <div className="mt-4 text-xs uppercase tracking-wider text-fg-subtle">Delivered in</div>
                <p className="mt-1 text-sm text-fg">
                  Phase {feature.phase}: {feature.phase_title}
                </p>
              </>
            ) : null}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-xs uppercase tracking-wider text-fg-subtle">Planned capabilities</div>
            <ul className="mt-2 space-y-1.5 text-sm text-fg-muted">
              {(feature?.capabilities ?? []).map((capability) => (
                <li key={capability} className="flex gap-2">
                  <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-fg-subtle" />
                  {capability}
                </li>
              ))}
            </ul>
            <p className="mt-4 text-xs text-fg-subtle">
              Nothing in this section can be used yet. The roadmap is in docs/ROADMAP.md.
            </p>
          </div>
        </div>
      </Panel>
    </>
  );
}
