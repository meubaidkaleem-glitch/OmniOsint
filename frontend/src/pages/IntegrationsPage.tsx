import { ExternalLink } from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

import { useProviders } from "@/api/queries";
import type { ProviderOut } from "@/api/types";
import { EmptyState, ErrorState, Notice } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form";
import { Badge, PageHeader, Panel, Skeleton } from "@/components/ui/surface";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

const STATUS_TONE: Record<ProviderOut["status"], "ok" | "neutral" | "danger"> = {
  available: "ok",
  planned: "neutral",
  excluded: "danger",
};

export function IntegrationsPage() {
  const providers = useProviders();
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const query = useDeferredValue(search.trim().toLowerCase());

  const items = useMemo(() => {
    return (providers.data?.items ?? []).filter(
      (provider) =>
        (!category || provider.category === category) &&
        (!status || provider.status === status) &&
        (!query ||
          provider.name.toLowerCase().includes(query) ||
          provider.id.includes(query) ||
          provider.notes.toLowerCase().includes(query)),
    );
  }, [providers.data, category, status, query]);

  return (
    <>
      <PageHeader
        title="Integrations"
        description="The provider control centre. In this phase it lists the data sources and tools OmniOSINT is designed to use, with the real status of each."
      />
      <Notice tone="info" title="No provider integration is implemented yet" className="mb-4">
        Credentials, health checks, quota and usage tracking arrive with the provider framework
        (Phase 2) and the first integrations (Phases 4 to 6). Access terms below are as publicly
        documented and are re-verified when each adapter is built.
      </Notice>

      {providers.isPending ? (
        <Skeleton className="h-96" />
      ) : providers.isError ? (
        <ErrorState error={providers.error} onRetry={() => void providers.refetch()} />
      ) : (
        <Panel
          title={`${providers.data.counts.total} catalogued sources`}
          description={`${providers.data.counts.available} available · ${providers.data.counts.planned} planned · ${providers.data.counts.excluded} excluded`}
          bodyClassName="p-0"
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Input
                aria-label="Search providers"
                placeholder="Search"
                className="h-8 w-44"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <Select
                aria-label="Category"
                className="h-8 w-56"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
              >
                <option value="">All categories</option>
                {providers.data.categories.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.label} ({item.count})
                  </option>
                ))}
              </Select>
              <Select
                aria-label="Status"
                className="h-8 w-40"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
              >
                <option value="">Any status</option>
                <option value="available">Available</option>
                <option value="planned">Planned</option>
                <option value="excluded">Excluded</option>
              </Select>
            </div>
          }
        >
          {items.length === 0 ? (
            <EmptyState title="No provider matches these filters." />
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>Provider</TH>
                  <TH>Category</TH>
                  <TH>Access</TH>
                  <TH>Phase</TH>
                  <TH>Status</TH>
                  <TH className="w-[40%]">Notes</TH>
                </tr>
              </THead>
              <TBody>
                {items.map((provider) => (
                  <TR key={provider.id}>
                    <TD>
                      <div className="font-medium text-fg">{provider.name}</div>
                      {provider.docs_url ? (
                        <a
                          href={provider.docs_url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                        >
                          Documentation <ExternalLink className="size-3" aria-hidden />
                        </a>
                      ) : null}
                    </TD>
                    <TD className="text-fg-muted">{provider.category_label}</TD>
                    <TD className="whitespace-nowrap text-fg-muted">{provider.access_label}</TD>
                    <TD className="tabular text-fg-muted">{provider.phase}</TD>
                    <TD>
                      <Badge tone={STATUS_TONE[provider.status]} className="capitalize">
                        {provider.status}
                      </Badge>
                    </TD>
                    <TD className="text-xs leading-relaxed text-fg-muted">
                      {provider.status === "planned" ? (
                        <span className="block text-fg-subtle">{provider.status_message}</span>
                      ) : null}
                      {provider.notes}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Panel>
      )}
    </>
  );
}
