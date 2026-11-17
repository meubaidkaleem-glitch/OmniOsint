import { ArrowRight, RefreshCw } from "lucide-react";
import { Link } from "react-router";

import { useCan } from "@/app/context";
import { useDashboard } from "@/api/queries";
import type { DashboardResponse, Metric } from "@/api/types";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState } from "@/components/ui/feedback";
import { Badge, PageHeader, Panel, Skeleton, StatusBadge, StatusDot } from "@/components/ui/surface";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatRelative, humanizeAction } from "@/lib/format";

function MetricTile({ metric }: { metric: Metric }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <div className="text-xs text-fg-muted">{metric.label}</div>
      <div className="mt-1 text-2xl font-semibold tabular text-fg">{metric.value}</div>
    </div>
  );
}

function HealthPanel({ data }: { data: DashboardResponse }) {
  const canReadSystem = useCan()("system:read");
  return (
    <Panel
      title="System health"
      description={`Checked ${formatRelative(data.health.checked_at)}`}
      actions={<StatusBadge status={data.health.status} />}
      bodyClassName="p-0"
    >
      <ul className="divide-y divide-line">
        {data.health.components.map((component) => (
          <li key={component.name} className="flex items-start gap-3 px-4 py-2.5">
            <StatusDot status={component.status} className="mt-1.5" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-sm text-fg">
                {component.label}
                {!component.required ? <span className="text-xs text-fg-subtle">optional</span> : null}
              </div>
              {component.detail ? (
                <div className="mt-0.5 text-xs text-fg-muted">{component.detail}</div>
              ) : null}
            </div>
            <span className="shrink-0 text-xs text-fg-subtle">
              {component.status.replace("_", " ")}
            </span>
          </li>
        ))}
      </ul>
      {canReadSystem ? (
        <div className="border-t border-line px-4 py-2 text-right">
          <Link to="/admin/system" className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
            System status <ArrowRight className="size-3" />
          </Link>
        </div>
      ) : null}
    </Panel>
  );
}

function PlannedMetrics({ metrics }: { metrics: Metric[] }) {
  return (
    <Panel
      title="Not yet available"
      description="These figures need modules that are not built yet. They are not shown as zero."
      bodyClassName="p-0"
    >
      <ul className="divide-y divide-line">
        {metrics.map((metric) => (
          <li key={metric.key} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
            <span className="text-fg-muted">{metric.label}</span>
            <span className="text-xs text-fg-subtle" title={metric.phase_title ?? undefined}>
              Phase {metric.planned_phase}
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function ActivityPanel({ data }: { data: DashboardResponse }) {
  const canReadAudit = useCan()("audit:read");
  return (
    <Panel
      title="Recent activity"
      description={data.activity_scope === "all" ? "All users" : "Your own activity"}
      actions={
        canReadAudit ? (
          <Link to="/admin/audit" className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
            Audit log <ArrowRight className="size-3" />
          </Link>
        ) : null
      }
      bodyClassName="p-0"
    >
      {data.recent_activity.length === 0 ? (
        <EmptyState title="No activity recorded yet." />
      ) : (
        <Table>
          <THead>
            <tr>
              <TH>When</TH>
              <TH>Action</TH>
              <TH>By</TH>
              <TH>Result</TH>
            </tr>
          </THead>
          <TBody>
            {data.recent_activity.map((item) => (
              <TR key={item.id}>
                <TD className="whitespace-nowrap text-fg-muted">{formatRelative(item.occurred_at)}</TD>
                <TD>
                  <span className="text-fg">{humanizeAction(item.action)}</span>
                  <span className="ml-2 font-mono text-xs text-fg-subtle">{item.action}</span>
                </TD>
                <TD className="text-fg-muted">{item.actor_label}</TD>
                <TD>
                  <Badge tone={item.outcome === "success" ? "ok" : item.outcome === "denied" ? "warn" : "danger"}>
                    {item.outcome}
                  </Badge>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </Panel>
  );
}

function PlatformPanel({ data }: { data: DashboardResponse }) {
  const { modules, providers } = data;
  return (
    <Panel title="Platform coverage" description="What exists today, from the feature and provider registries.">
      <div className="space-y-4 text-sm">
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-fg-muted">Interface sections</span>
            <span className="tabular text-fg">
              {modules.available + modules.partial} of {modules.available + modules.partial + modules.planned} built
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Badge tone="ok">{modules.available} available</Badge>
            <Badge tone="accent">{modules.partial} partial</Badge>
            <Badge>{modules.planned} planned</Badge>
          </div>
        </div>
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-fg-muted">Provider integrations</span>
            <span className="tabular text-fg">
              {providers.available} of {providers.total} catalogued
            </span>
          </div>
          <p className="text-xs text-fg-muted">
            {providers.available === 0
              ? "No provider integration is implemented yet. The first ones arrive in Phases 4 to 6."
              : `${providers.available} integrations available.`}
          </p>
          <Link to="/integrations" className="mt-2 inline-flex items-center gap-1 text-xs text-accent hover:underline">
            Provider catalogue <ArrowRight className="size-3" />
          </Link>
        </div>
      </div>
    </Panel>
  );
}

export function DashboardPage() {
  const dashboard = useDashboard();

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="System health and activity. Every number on this page comes from a database record."
        actions={
          <Button
            size="sm"
            icon={<RefreshCw className="size-3.5" />}
            onClick={() => void dashboard.refetch()}
            loading={dashboard.isFetching && !dashboard.isPending}
          >
            Refresh
          </Button>
        }
      />
      {dashboard.isPending ? (
        <div className="grid gap-4 md:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-20" />
          ))}
          <Skeleton className="h-64 md:col-span-2" />
          <Skeleton className="h-64 md:col-span-2" />
        </div>
      ) : dashboard.isError ? (
        <ErrorState error={dashboard.error} onRetry={() => void dashboard.refetch()} />
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {dashboard.data.metrics
              .filter((metric) => metric.available)
              .map((metric) => (
                <MetricTile key={metric.key} metric={metric} />
              ))}
          </div>
          <div className="grid gap-4 xl:grid-cols-3">
            <div className="space-y-4 xl:col-span-2">
              <HealthPanel data={dashboard.data} />
              <ActivityPanel data={dashboard.data} />
            </div>
            <div className="space-y-4">
              <PlatformPanel data={dashboard.data} />
              <PlannedMetrics metrics={dashboard.data.metrics.filter((metric) => !metric.available)} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
