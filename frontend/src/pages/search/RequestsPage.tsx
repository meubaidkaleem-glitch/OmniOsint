import { Link } from "react-router";

import { useCollectionRequests } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState } from "@/components/ui/feedback";
import { Badge, Panel, Skeleton } from "@/components/ui/surface";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { REQUEST_STATUS, statusOf, useTypeLabel } from "@/lib/collection";
import { formatDateTime } from "@/lib/format";

export function RequestsPage() {
  const requests = useCollectionRequests();
  const typeLabel = useTypeLabel();
  if (requests.isPending) return <Skeleton className="h-64" />;
  if (requests.isError) return <ErrorState error={requests.error} onRetry={() => void requests.refetch()} />;
  const items = requests.data.pages.flatMap((page) => page.items);
  if (!items.length) {
    return (
      <EmptyState title="No collection has been run yet">
        Requests appear here when a plan is run from the Search tab or with{" "}
        <code>omniosint investigate</code>.
      </EmptyState>
    );
  }
  return (
    <Panel title="Collection requests" description="Every plan that was run, newest first." bodyClassName="p-0">
      <div className="overflow-x-auto">
        <Table>
          <THead>
            <TR>
              <TH>Indicator</TH>
              <TH>Type</TH>
              <TH>Mode</TH>
              <TH>Status</TH>
              <TH>Started</TH>
            </TR>
          </THead>
          <TBody>
            {items.map((item) => {
              const status = statusOf(REQUEST_STATUS, item.status);
              return (
                <TR key={item.id}>
                  <TD className="max-w-80 truncate">
                    <Link className="text-accent hover:underline" to={`/search/requests/${item.id}`}>
                      {item.indicator_value}
                    </Link>
                    {item.is_simulated ? (
                      <Badge tone="warn" className="ml-2">
                        Simulated
                      </Badge>
                    ) : null}
                  </TD>
                  <TD className="text-fg-muted">{typeLabel(item.indicator_type)}</TD>
                  <TD className="text-fg-muted">{item.mode}</TD>
                  <TD>
                    <Badge tone={status.tone}>{status.label}</Badge>
                  </TD>
                  <TD className="whitespace-nowrap text-fg-muted">{formatDateTime(item.created_at)}</TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      </div>
      {requests.hasNextPage ? (
        <div className="border-t border-line p-3">
          <Button size="sm" onClick={() => void requests.fetchNextPage()} loading={requests.isFetchingNextPage}>
            Show more
          </Button>
        </div>
      ) : null}
    </Panel>
  );
}
