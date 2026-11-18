import { useQuery } from "@tanstack/react-query";
import { Bookmark, History, Play, Search, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";

import { api } from "@/api/client";
import {
  useClassify,
  useClearHistory,
  useDeleteSavedSearch,
  useSaveSearch,
  useSavedSearches,
  useScopes,
  useSearchHistory,
  useSubmitCollection,
} from "@/api/queries";
import type { CandidateOut, ClassificationOut, PlanOut, PlanRequest } from "@/api/types";
import { useCan } from "@/app/context";
import { Button, IconButton } from "@/components/ui/button";
import { ErrorState, FormError, Notice } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/form";
import { Badge, Panel, Skeleton } from "@/components/ui/surface";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import {
  RANK_TONE,
  SIMULATION_MODES,
  STEP_STATUS,
  statusOf,
  useDebouncedValue,
} from "@/lib/collection";
import { cn, formatRelative } from "@/lib/format";

interface PlanOptions {
  mode: "passive" | "active";
  scopeId: string;
  includePaid: boolean;
  forceRefresh: boolean;
  simulate: string;
}

const DEFAULT_OPTIONS: PlanOptions = {
  mode: "passive",
  scopeId: "",
  includePaid: false,
  forceRefresh: false,
  simulate: "",
};

function planRequest(input: string, type: string, options: PlanOptions): PlanRequest {
  return {
    input,
    type: type as PlanRequest["type"],
    mode: options.mode,
    strategy: options.includePaid ? "include_paid" : "free_first",
    scope_id: options.mode === "active" && options.scopeId ? options.scopeId : null,
    force_refresh: options.forceRefresh,
    provider_options: options.simulate ? { simulate: options.simulate } : {},
  };
}

/** Remounts the page on every navigation to it, so ?q= from the command palette applies. */
export function SearchRoute() {
  const [params] = useSearchParams();
  const location = useLocation();
  return <SearchPage key={location.key} initialQuery={params.get("q") ?? ""} />;
}

export function SearchPage({ initialQuery = "" }: { initialQuery?: string }) {
  const can = useCan();
  const navigate = useNavigate();
  const [text, setText] = useState(initialQuery);
  const [chosen, setChosen] = useState<{ input: string; type: string } | null>(null);
  const [options, setOptions] = useState<PlanOptions>(DEFAULT_OPTIONS);
  const input = useDebouncedValue(text.trim(), 300);
  const remember = useClassify();

  const classification = useQuery({
    queryKey: ["search", "classify", input],
    queryFn: ({ signal: _signal }) =>
      api.post<ClassificationOut>("/search/classify", { input, remember: false }),
    enabled: input.length > 0,
    staleTime: 60_000,
  });

  const result = classification.data && input ? classification.data : null;
  // The reading in use: the user's choice for this input, else the classifier's
  // unambiguous result. An ambiguous input waits for a choice.
  const selected: CandidateOut | null = useMemo(() => {
    if (!result) return null;
    if (chosen && chosen.input === input) {
      return result.candidates.find((candidate) => candidate.type === chosen.type) ?? null;
    }
    return result.status === "recognized" ? (result.candidates[0] ?? null) : null;
  }, [result, chosen, input]);

  const request = selected ? planRequest(input, selected.type, options) : null;
  const plan = useQuery({
    queryKey: ["collection", "plan", request],
    queryFn: () => api.post<PlanOut>("/collection/plan", request),
    enabled: request !== null && selected?.type !== "question" && !["file", "image", "document"].includes(selected?.type ?? ""),
    retry: false,
  });
  const submit = useSubmitCollection();

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    remember.mutate({ input: value, remember: true });
  }

  function run() {
    if (!request) return;
    submit.mutate(request, { onSuccess: (created) => void navigate(`/search/requests/${created.id}`) });
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_18rem]">
      <div className="min-w-0 space-y-5">
        <form onSubmit={onSubmit} className="flex gap-2" role="search">
          <div className="relative min-w-0 flex-1">
            <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" />
            <Input
              autoFocus
              aria-label="Indicator"
              placeholder="Email, phone, domain, URL, IP or range, AS number, hash, CVE, package, coordinates..."
              className="h-11 pl-9 text-base"
              value={text}
              maxLength={2000}
              onChange={(event) => setText(event.target.value)}
            />
          </div>
          <Button type="submit" variant="primary" className="h-11" disabled={!text.trim()}>
            Classify
          </Button>
        </form>

        {!input ? (
          <Notice tone="info" title="Nothing is collected until you run a plan">
            Classification happens on this computer. The plan lists every source that could serve
            the indicator, with the reason each would or would not be used.
          </Notice>
        ) : classification.isError ? (
          <ErrorState error={classification.error} onRetry={() => void classification.refetch()} />
        ) : !result ? (
          <Skeleton className="h-32" />
        ) : (
          <ClassificationPanel
            result={result}
            selected={selected}
            onChoose={(type) => setChosen({ input, type })}
          />
        )}

        {selected ? (
          <PlanPanel
            selected={selected}
            options={options}
            onOptions={setOptions}
            plan={plan.data ?? null}
            loading={plan.isFetching && !plan.data}
            error={plan.error}
            canRun={can("collection:run")}
            running={submit.isPending}
            runError={submit.error}
            onRun={run}
          />
        ) : null}
      </div>
      <SidePanels
        current={text.trim()}
        currentType={selected?.type ?? null}
        onPick={(query) => {
          setText(query);
          setChosen(null);
        }}
      />
    </div>
  );
}

function ClassificationPanel({
  result,
  selected,
  onChoose,
}: {
  result: ClassificationOut;
  selected: CandidateOut | null;
  onChoose: (type: string) => void;
}) {
  return (
    <Panel title="Classification" description={result.message}>
      {result.status === "unrecognized" ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-fg-muted">
          {result.hints.map((hint) => (
            <li key={hint}>{hint}</li>
          ))}
        </ul>
      ) : (
        <fieldset className="space-y-2">
          <legend className="sr-only">Readings of the input</legend>
          {result.status === "ambiguous" ? (
            <Notice tone="warn" className="mb-2">
              The input can mean more than one thing. Choose the reading you mean; nothing is guessed.
            </Notice>
          ) : null}
          {result.candidates.map((candidate) => {
            const active = selected?.type === candidate.type;
            return (
              <label
                key={`${candidate.type}:${candidate.value}`}
                className={cn(
                  "flex cursor-pointer gap-3 rounded-md border p-3 transition-colors",
                  active ? "border-accent bg-accent-soft/40" : "border-line hover:border-line-strong",
                )}
              >
                <input
                  type="radio"
                  name="reading"
                  className="mt-1"
                  checked={active}
                  onChange={() => onChoose(candidate.type)}
                />
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-fg">{candidate.label}</span>
                    <Badge tone={RANK_TONE[candidate.rank] ?? "neutral"}>{candidate.rank}</Badge>
                    <code className="break-all text-xs text-fg-muted">{candidate.display}</code>
                  </div>
                  <p className="text-xs text-fg-muted">{candidate.reason}</p>
                  {candidate.notes.length ? (
                    <ul className="list-disc space-y-0.5 pl-4 text-xs text-fg-subtle">
                      {candidate.notes.map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </label>
            );
          })}
          {result.mentions.length ? (
            <div className="pt-2 text-sm">
              <p className="mb-1 text-fg-muted">Indicators mentioned:</p>
              <div className="flex flex-wrap gap-1.5">
                {result.mentions.map((mention) => (
                  <Badge key={`${mention.type}:${mention.value}`}>
                    {mention.label}: {mention.display}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}
        </fieldset>
      )}
    </Panel>
  );
}

function PlanPanel({
  selected,
  options,
  onOptions,
  plan,
  loading,
  error,
  canRun,
  running,
  runError,
  onRun,
}: {
  selected: CandidateOut;
  options: PlanOptions;
  onOptions: (options: PlanOptions) => void;
  plan: PlanOut | null;
  loading: boolean;
  error: unknown;
  canRun: boolean;
  running: boolean;
  runError: unknown;
  onRun: () => void;
}) {
  const can = useCan();
  const scopes = useScopes(options.mode === "active" && can("scopes:read"));
  const activeScopes = (scopes.data?.items ?? []).filter((scope) => scope.status === "active");
  const simulatedOffered = plan?.steps.some((step) => step.simulated) ?? false;
  const selectedSteps = plan?.steps.filter((step) => step.selected) ?? [];

  if (selected.type === "question" || ["file", "image", "document"].includes(selected.type)) {
    return (
      <Notice tone="info" title="No collection for this kind of input yet">
        {selected.type === "question"
          ? "Questions are answered by the AI investigation engine (Phase 10). Investigate the indicators it mentions instead."
          : "Files are examined from uploads, which arrive in Phase 9."}
      </Notice>
    );
  }

  return (
    <Panel
      title="Collection plan"
      description={plan ? `${plan.indicator.label}: ${plan.indicator.display}` : "Computing..."}
      actions={
        <Button
          variant="primary"
          onClick={onRun}
          loading={running}
          disabled={!canRun || !selectedSteps.length}
          icon={<Play aria-hidden className="size-4" />}
          title={canRun ? undefined : "Running collection needs the collection:run permission"}
        >
          {selectedSteps.length ? `Run ${selectedSteps.length} step${selectedSteps.length === 1 ? "" : "s"}` : "Nothing to run"}
        </Button>
      }
      bodyClassName="space-y-4"
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field
          label="Mode"
          hint={
            options.mode === "passive"
              ? "The target is not contacted."
              : "May contact the target: needs a scope and an approval."
          }
        >
          {(props) => (
            <Select
              {...props}
              value={options.mode}
              onChange={(event) => onOptions({ ...options, mode: event.target.value as PlanOptions["mode"] })}
            >
              <option value="passive">Passive</option>
              <option value="active">Active</option>
            </Select>
          )}
        </Field>
        {options.mode === "active" ? (
          <Field label="Scope" hint={activeScopes.length ? undefined : "No active scope is recorded."}>
            {(props) => (
              <Select
                {...props}
                value={options.scopeId}
                onChange={(event) => onOptions({ ...options, scopeId: event.target.value })}
              >
                <option value="">No scope</option>
                {activeScopes.map((scope) => (
                  <option key={scope.id} value={scope.id}>
                    {scope.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        ) : null}
        <div className="flex flex-col justify-end gap-2 pb-1">
          <Checkbox
            label="Include paid sources"
            checked={options.includePaid}
            onChange={(event) => onOptions({ ...options, includePaid: event.target.checked })}
          />
          <Checkbox
            label="Ignore cached results"
            checked={options.forceRefresh}
            onChange={(event) => onOptions({ ...options, forceRefresh: event.target.checked })}
          />
        </div>
        {simulatedOffered ? (
          <Field label="Simulated provider behaviour" hint="For testing the pipeline only.">
            {(props) => (
              <Select
                {...props}
                value={options.simulate}
                onChange={(event) => onOptions({ ...options, simulate: event.target.value })}
              >
                {SIMULATION_MODES.map((mode) => (
                  <option key={mode.value} value={mode.value}>
                    {mode.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        ) : null}
      </div>

      {error ? <ErrorState error={error} /> : null}
      <FormError error={runError} />
      {loading ? <Skeleton className="h-40" /> : null}
      {plan ? (
        <>
          {plan.warnings.map((warning) => (
            <Notice key={warning} tone="warn">
              {warning}
            </Notice>
          ))}
          <div className="overflow-x-auto rounded-md border border-line">
            <Table>
              <THead>
                <TR>
                  <TH>Source</TH>
                  <TH>Capability</TH>
                  <TH>Status</TH>
                  <TH>Why</TH>
                </TR>
              </THead>
              <TBody>
                {plan.steps.map((step) => {
                  const status = statusOf(STEP_STATUS, step.status);
                  return (
                    <TR key={`${step.provider_id}:${step.capability_id ?? "catalogue"}`}>
                      <TD className="whitespace-nowrap">
                        {step.provider_name}
                        {step.simulated ? (
                          <Badge tone="warn" className="ml-2">
                            Simulated
                          </Badge>
                        ) : null}
                      </TD>
                      <TD className="text-fg-muted">{step.capability_name ?? "-"}</TD>
                      <TD>
                        <Badge tone={status.tone}>{status.label}</Badge>
                      </TD>
                      <TD className="text-xs text-fg-muted">
                        {step.message}
                        {step.phase ? ` Phase ${step.phase}.` : ""}
                      </TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
          </div>
          <p className="text-xs text-fg-subtle">
            Modules for this input:{" "}
            {plan.modules.map((module) => `${module.title} (Phase ${module.phase})`).join(", ")}.
          </p>
        </>
      ) : null}
    </Panel>
  );
}

function SidePanels({
  current,
  currentType,
  onPick,
}: {
  current: string;
  currentType: string | null;
  onPick: (query: string) => void;
}) {
  const history = useSearchHistory();
  const clear = useClearHistory();
  const saved = useSavedSearches();
  const save = useSaveSearch();
  const remove = useDeleteSavedSearch();
  const [name, setName] = useState("");

  return (
    <aside className="space-y-5">
      <Panel
        title="Recent searches"
        actions={
          history.data?.items.length ? (
            <IconButton label="Clear search history" onClick={() => clear.mutate()}>
              <Trash2 className="size-4" />
            </IconButton>
          ) : null
        }
        bodyClassName="p-2"
      >
        {history.data?.items.length ? (
          <ul className="space-y-0.5">
            {history.data.items.map((entry) => (
              <li key={entry.id}>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-surface-3"
                  onClick={() => onPick(entry.query)}
                >
                  <History aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
                  <span className="min-w-0 flex-1 truncate">{entry.query}</span>
                  <span className="shrink-0 text-[11px] text-fg-subtle">{formatRelative(entry.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-2 py-1 text-sm text-fg-muted">Searches you classify or run appear here.</p>
        )}
      </Panel>
      <Panel title="Saved searches" bodyClassName="space-y-3 p-3">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!name.trim() || !current) return;
            save.mutate(
              { name: name.trim(), query: current, indicator_type: (currentType ?? null) as never, options: {} },
              { onSuccess: () => setName("") },
            );
          }}
        >
          <Input
            aria-label="Name for this search"
            placeholder="Name this search"
            className="h-8"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <IconButton label="Save the current search" type="submit" disabled={!name.trim() || !current}>
            <Bookmark className="size-4" />
          </IconButton>
        </form>
        <FormError error={save.error} />
        {saved.data?.items.length ? (
          <ul className="space-y-0.5">
            {saved.data.items.map((item) => (
              <li key={item.id} className="flex items-center gap-1">
                <button
                  type="button"
                  className="min-w-0 flex-1 truncate rounded px-2 py-1.5 text-left text-sm hover:bg-surface-3"
                  onClick={() => onPick(item.query)}
                  title={item.query}
                >
                  {item.name}
                </button>
                <IconButton label={`Delete saved search ${item.name}`} onClick={() => remove.mutate(item.id)}>
                  <Trash2 className="size-3.5" />
                </IconButton>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-fg-muted">No saved searches.</p>
        )}
      </Panel>
    </aside>
  );
}
