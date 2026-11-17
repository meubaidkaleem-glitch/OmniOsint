import { RefreshCw } from "lucide-react";

import { useCan } from "@/app/context";
import { useSystemStatus } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { ErrorState, Notice } from "@/components/ui/feedback";
import { DefinitionList, Panel, Skeleton, StatusBadge, StatusDot } from "@/components/ui/surface";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatDateTime, formatDuration } from "@/lib/format";
import { NoAccessPage } from "@/pages/MiscPages";

export function SystemPage() {
  const can = useCan();
  const status = useSystemStatus();
  if (!can("system:read")) return <NoAccessPage permission="system:read" />;
  if (status.isPending) return <Skeleton className="h-80" />;
  if (status.isError) return <ErrorState error={status.error} onRetry={() => void status.refetch()} />;
  const data = status.data;

  return (
    <div className="space-y-4">
      {!data.server.local_only ? (
        <Notice tone="warn" title="The interface is reachable from other machines">
          OmniOSINT is listening on {data.server.host}. It has no TLS of its own; use 127.0.0.1 unless it
          runs behind a reverse proxy you control.
        </Notice>
      ) : null}
      <Panel
        title="Components"
        description={`Checked ${formatDateTime(data.checked_at)}`}
        bodyClassName="p-0"
        actions={
          <>
            <StatusBadge status={data.status} />
            <Button
              size="sm"
              icon={<RefreshCw className="size-3.5" />}
              onClick={() => void status.refetch()}
              loading={status.isFetching}
            >
              Check now
            </Button>
          </>
        }
      >
        <Table>
          <THead>
            <tr>
              <TH>Component</TH>
              <TH>Status</TH>
              <TH>Detail</TH>
              <TH className="text-right">Latency</TH>
            </tr>
          </THead>
          <TBody>
            {data.components.map((component) => (
              <TR key={component.name}>
                <TD>
                  <div className="flex items-center gap-2 text-fg">
                    <StatusDot status={component.status} />
                    {component.label}
                  </div>
                  <div className="ml-4 text-xs text-fg-subtle">{component.required ? "required" : "optional"}</div>
                </TD>
                <TD className="whitespace-nowrap text-fg-muted">{component.status.replace("_", " ")}</TD>
                <TD className="text-fg-muted">{component.detail}</TD>
                <TD className="text-right tabular text-fg-muted">
                  {component.latency_ms !== null ? `${component.latency_ms.toFixed(1)} ms` : "—"}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Service">
          <DefinitionList
            items={[
              ["Version", data.version],
              ["Environment", data.environment],
              ["Running since", `${formatDateTime(data.started_at)} (${formatDuration(data.uptime_seconds)})`],
              ["Listening on", `${data.server.host}:${data.server.port}${data.server.local_only ? " (this computer only)" : ""}`],
            ]}
          />
        </Panel>
        <Panel title="Runtime">
          <DefinitionList
            items={[
              ["Python", data.runtime.python],
              ["Platform", data.runtime.platform],
              ["Process ID", data.runtime.pid],
              ["Data directory", <code key="d" className="break-all text-xs">{data.data_directory}</code>],
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
