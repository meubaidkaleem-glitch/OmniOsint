import { useDeferredValue, useState } from "react";

import { useCan } from "@/app/context";
import { useAuditEvents } from "@/api/queries";
import type { AuditEventOut } from "@/api/types";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form";
import { Dialog } from "@/components/ui/overlay";
import { Badge, DefinitionList, Panel, Skeleton } from "@/components/ui/surface";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";
import { NoAccessPage } from "@/pages/MiscPages";

const CATEGORIES = ["auth", "authz", "user", "backup", "system"];

function OutcomeBadge({ outcome }: { outcome: string }) {
  return (
    <Badge tone={outcome === "success" ? "ok" : outcome === "denied" ? "warn" : "danger"}>{outcome}</Badge>
  );
}

export function AuditPage() {
  const can = useCan();
  const [category, setCategory] = useState("");
  const [outcome, setOutcome] = useState("");
  const [action, setAction] = useState("");
  const deferredAction = useDeferredValue(action.trim());
  const events = useAuditEvents({ category, outcome, action: deferredAction });
  const [selected, setSelected] = useState<AuditEventOut | null>(null);

  if (!can("audit:read")) return <NoAccessPage permission="audit:read" />;
  const rows = events.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <>
      <Panel
        title="Audit log"
        description="Security-relevant actions, newest first. Entries cannot be changed or removed."
        bodyClassName="p-0"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Select aria-label="Category" className="h-8 w-44" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">All categories</option>
              {CATEGORIES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
            <Select aria-label="Outcome" className="h-8 w-40" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="">Any outcome</option>
              <option value="success">Success</option>
              <option value="failure">Failure</option>
              <option value="denied">Denied</option>
            </Select>
            <Input
              aria-label="Exact action"
              placeholder="Exact action, e.g. auth.login.failure"
              className="h-8 w-64 font-mono text-xs"
              value={action}
              onChange={(e) => setAction(e.target.value)}
            />
          </div>
        }
      >
        {events.isPending ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }, (_, index) => (
              <Skeleton key={index} className="h-7" />
            ))}
          </div>
        ) : events.isError ? (
          <div className="p-4">
            <ErrorState error={events.error} onRetry={() => void events.refetch()} />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState title="No audit events match these filters." />
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>Time</TH>
                <TH>Action</TH>
                <TH>Outcome</TH>
                <TH>Actor</TH>
                <TH>Target</TH>
                <TH>Address</TH>
              </tr>
            </THead>
            <TBody>
              {rows.map((event) => (
                <TR key={event.id} className="cursor-pointer" onClick={() => setSelected(event)}>
                  <TD className="whitespace-nowrap tabular text-fg-muted">{formatDateTime(event.occurred_at)}</TD>
                  <TD className="font-mono text-xs text-fg">{event.action}</TD>
                  <TD>
                    <OutcomeBadge outcome={event.outcome} />
                  </TD>
                  <TD className="text-fg-muted">{event.actor_label}</TD>
                  <TD className="text-xs text-fg-subtle">
                    {event.target_type ? `${event.target_type}` : "—"}
                  </TD>
                  <TD className="font-mono text-xs text-fg-subtle">{event.ip_address ?? "—"}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
        {events.hasNextPage ? (
          <div className="border-t border-line p-3 text-center">
            <Button size="sm" onClick={() => void events.fetchNextPage()} loading={events.isFetchingNextPage}>
              Load older entries
            </Button>
          </div>
        ) : null}
      </Panel>

      {selected ? (
        <Dialog open onOpenChange={(open) => !open && setSelected(null)} title={selected.action} width="max-w-2xl">
          <DefinitionList
            items={[
              ["Time", formatDateTime(selected.occurred_at)],
              ["Outcome", <OutcomeBadge key="o" outcome={selected.outcome} />],
              ["Actor", selected.actor_label],
              ["Target", selected.target_type ? `${selected.target_type} ${selected.target_id ?? ""}` : "—"],
              ["Address", selected.ip_address ?? "—"],
              ["Client", selected.user_agent ?? "—"],
              ["Request ID", <code key="r" className="text-xs">{selected.request_id ?? "—"}</code>],
              ["Event ID", <code key="i" className="text-xs">{selected.id}</code>],
            ]}
          />
          <div className="mt-4 text-xs uppercase tracking-wider text-fg-subtle">Details</div>
          <pre className="mt-1 overflow-x-auto rounded-md border border-line bg-surface-2 p-3 text-xs text-fg-muted">
            {JSON.stringify(selected.details, null, 2)}
          </pre>
        </Dialog>
      ) : null}
    </>
  );
}
