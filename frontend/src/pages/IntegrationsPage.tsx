import { ExternalLink } from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

import { useAdapters, useHealthCheck, useProviders } from "@/api/queries";
import type { AdapterOut, HealthOut, ProviderOut } from "@/api/types";
import { useCan } from "@/app/context";
import { Button } from "@/components/ui/button";
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
  const can = useCan();
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
      <Notice tone="info" title="No real provider integration is implemented yet" className="mb-4">
        The provider framework is in place: adapters below are what can collect. The first real
        integrations arrive in Phases 4 to 6 and credentials are managed from Phase 5. Access terms
        in the catalogue are as publicly documented and are re-verified when each adapter is built.
      </Notice>
      {can("collection:read") ? <AdaptersPanel /> : null}

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

const ADAPTER_TONE: Record<AdapterOut["status"], "ok" | "warn" | "neutral"> = {
  available: "ok",
  not_configured: "warn",
  disabled: "neutral",
};

function AdaptersPanel() {
  const can = useCan();
  const adapters = useAdapters();
  const check = useHealthCheck();
  const [results, setResults] = useState<Record<string, HealthOut>>({});

  if (adapters.isPending) return <Skeleton className="mb-4 h-24" />;
  if (adapters.isError) return <ErrorState error={adapters.error} />;
  return (
    <Panel
      title="Installed adapters"
      description="The code that can collect, with its real state. Real providers start in Phase 4."
      className="mb-4"
      bodyClassName="p-0"
    >
      <Table>
        <THead>
          <tr>
            <TH>Adapter</TH>
            <TH>Status</TH>
            <TH>Capabilities</TH>
            <TH>Today</TH>
            <TH>Health</TH>
          </tr>
        </THead>
        <TBody>
          {adapters.data.items.map((adapter) => (
            <TR key={adapter.id}>
              <TD>
                <div className="font-medium text-fg">{adapter.name}</div>
                <div className="text-xs text-fg-muted">{adapter.description}</div>
                {adapter.simulated ? (
                  <Badge tone="warn" className="mt-1">
                    Simulated test data
                  </Badge>
                ) : null}
              </TD>
              <TD>
                <Badge tone={ADAPTER_TONE[adapter.status]}>{adapter.status.replace("_", " ")}</Badge>
                <div className="mt-1 text-xs text-fg-subtle">{adapter.message}</div>
                {adapter.circuit !== "closed" ? (
                  <div className="text-xs text-warn">Circuit {adapter.circuit.replace("_", "-")}</div>
                ) : null}
              </TD>
              <TD className="text-xs text-fg-muted">
                {adapter.capabilities.map((capability) => (
                  <div key={capability.id}>
                    {capability.name}
                    {capability.active ? " (active, needs a scope)" : ""}
                    {capability.cost.kind !== "free" ? ` (${capability.cost.kind})` : ""}
                  </div>
                ))}
              </TD>
              <TD className="tabular whitespace-nowrap text-xs text-fg-muted">
                {String(adapter.usage_today.requests ?? 0)} calls, {String(adapter.usage_today.failures ?? 0)} failed,{" "}
                {String(adapter.usage_today.cache_hits ?? 0)} cached
              </TD>
              <TD className="text-xs">
                {can("collection:run") && adapter.status === "available" ? (
                  <Button
                    size="sm"
                    loading={check.isPending && check.variables === adapter.id}
                    onClick={() =>
                      check.mutate(adapter.id, {
                        onSuccess: (result) => setResults((current) => ({ ...current, [adapter.id]: result })),
                      })
                    }
                  >
                    Check
                  </Button>
                ) : null}
                {results[adapter.id] ? (
                  <div className="mt-1 text-fg-muted">
                    {results[adapter.id]?.status}: {results[adapter.id]?.detail}
                  </div>
                ) : null}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </Panel>
  );
}
