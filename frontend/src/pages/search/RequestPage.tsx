import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import {
  useCancelRequest,
  useCollectionRequest,
  useJob,
  useJobAction,
  useJobEvidence,
} from "@/api/queries";
import type { JobOut } from "@/api/types";
import { useCan } from "@/app/context";
import { Button } from "@/components/ui/button";
import { ErrorState, FormError, Notice } from "@/components/ui/feedback";
import { Badge, DefinitionList, Panel, Skeleton } from "@/components/ui/surface";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { JOB_STATUS, REQUEST_STATUS, STEP_STATUS, statusOf } from "@/lib/collection";
import { cn, formatDateTime } from "@/lib/format";

const FINISHED = new Set(["succeeded", "failed", "cancelled", "skipped"]);

interface PlanStepSnapshot {
  provider_id: string;
  provider_name: string;
  capability_id: string | null;
  capability_name: string | null;
  status: string;
  message: string;
  phase: number | null;
  selected: boolean;
}

export function RequestPage() {
  const { requestId = "" } = useParams();
  const detail = useCollectionRequest(requestId);
  const cancel = useCancelRequest();
  const can = useCan();
  const [open, setOpen] = useState<string | null>(null);

  if (detail.isPending) return <Skeleton className="h-64" />;
  if (detail.isError) return <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />;
  const { request, jobs, plan } = detail.data;
  const status = statusOf(REQUEST_STATUS, request.status);
  const notRun = ((plan.steps ?? []) as PlanStepSnapshot[]).filter((step) => !step.selected);
  const unfinished = jobs.some((job) => !FINISHED.has(job.status));

  return (
    <div className="space-y-5">
      <Panel
        title={
          <span className="flex flex-wrap items-center gap-2">
            <span className="break-all">{request.indicator_value}</span>
            <Badge tone={status.tone}>{status.label}</Badge>
          </span>
        }
        description={`${request.indicator_type.replaceAll("_", " ")} · ${request.mode} mode · started ${formatDateTime(request.created_at)}`}
        actions={
          unfinished && can("collection:run") ? (
            <Button size="sm" variant="danger" onClick={() => cancel.mutate(request.id)} loading={cancel.isPending}>
              Cancel unfinished jobs
            </Button>
          ) : null
        }
        bodyClassName="space-y-3"
      >
        {request.is_simulated ? (
          <Notice tone="warn" title="Simulated data">
            Everything collected for this request came from the simulated provider. It is test data and
            describes nothing real.
          </Notice>
        ) : null}
        <FormError error={cancel.error} />
        <div className="overflow-x-auto rounded-md border border-line">
          <Table>
            <THead>
              <TR>
                <TH className="w-6" />
                <TH>Provider</TH>
                <TH>Capability</TH>
                <TH>Status</TH>
                <TH>Attempt</TH>
                <TH>Result</TH>
              </TR>
            </THead>
            <TBody>
              {jobs.map((job) => (
                <JobRow key={job.id} job={job} open={open === job.id} onToggle={() => setOpen(open === job.id ? null : job.id)} />
              ))}
            </TBody>
          </Table>
        </div>
      </Panel>
      {notRun.length ? (
        <Panel
          title="Not run"
          description="Sources in the plan that were not used, and why. Kept with the request as shown."
          bodyClassName="p-0"
        >
          <Table>
            <TBody>
              {notRun.map((step) => {
                const stepStatus = statusOf(STEP_STATUS, step.status);
                return (
                  <TR key={`${step.provider_id}:${step.capability_id ?? "catalogue"}`}>
                    <TD className="whitespace-nowrap">{step.provider_name}</TD>
                    <TD>
                      <Badge tone={stepStatus.tone}>{stepStatus.label}</Badge>
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
        </Panel>
      ) : null}
    </div>
  );
}

function resultText(job: JobOut): string {
  if (job.error) return String(job.error.message ?? job.error.code ?? "Failed");
  if (job.outcome) {
    if (job.outcome.from_cache) return `Reused a fresh earlier result (${String(job.outcome.items)} items)`;
    const truncated = job.outcome.truncated ? " (incomplete)" : "";
    return `${String(job.outcome.items)} observations, ${String(job.outcome.evidence)} evidence records${truncated}`;
  }
  if (job.status === "awaiting_approval") return "Waiting for approval";
  return "";
}

function JobRow({ job, open, onToggle }: { job: JobOut; open: boolean; onToggle: () => void }) {
  const status = statusOf(JOB_STATUS, job.status);
  return (
    <>
      <TR className="cursor-pointer" onClick={onToggle}>
        <TD>
          <button type="button" aria-label={open ? "Hide details" : "Show details"} aria-expanded={open}>
            {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </button>
        </TD>
        <TD className="whitespace-nowrap">
          {job.provider_id}
          {job.is_simulated ? (
            <Badge tone="warn" className="ml-2">
              Simulated
            </Badge>
          ) : null}
          {job.is_active ? (
            <Badge tone="danger" className="ml-2">
              Active
            </Badge>
          ) : null}
        </TD>
        <TD className="text-fg-muted">{job.capability}</TD>
        <TD>
          <Badge tone={status.tone}>{status.label}</Badge>
        </TD>
        <TD className="text-fg-muted">
          {job.attempt}/{job.max_attempts}
        </TD>
        <TD className={cn("text-xs", job.error ? "text-danger" : "text-fg-muted")}>{resultText(job)}</TD>
      </TR>
      {open ? (
        <TR>
          <TD colSpan={6} className="bg-surface-2">
            <JobDetail jobId={job.id} />
          </TD>
        </TR>
      ) : null}
    </>
  );
}

function JobDetail({ jobId }: { jobId: string }) {
  const detail = useJob(jobId);
  const evidence = useJobEvidence(jobId);
  const action = useJobAction();
  const can = useCan();
  if (detail.isPending) return <Skeleton className="h-24" />;
  if (detail.isError) return <ErrorState error={detail.error} />;
  const { job, events, results } = detail.data;
  return (
    <div className="space-y-4 py-2">
      <div className="flex flex-wrap gap-2">
        {job.status === "awaiting_approval" && can("collection:approve") ? (
          <Button size="sm" variant="primary" onClick={() => action.mutate({ id: job.id, action: "approve" })}>
            Approve
          </Button>
        ) : null}
        {!FINISHED.has(job.status) && can("collection:run") ? (
          <Button size="sm" variant="danger" onClick={() => action.mutate({ id: job.id, action: "cancel" })}>
            Cancel
          </Button>
        ) : null}
        {(job.status === "failed" || job.status === "cancelled") && can("collection:run") ? (
          <Button size="sm" onClick={() => action.mutate({ id: job.id, action: "retry" })}>
            Retry
          </Button>
        ) : null}
      </div>
      <FormError error={action.error} />
      {job.error ? (
        <Notice tone="danger" title={String(job.error.code ?? "Failed")}>
          {String(job.error.message ?? "")}
        </Notice>
      ) : null}
      <div>
        <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-fg-subtle">History</h3>
        <ol className="space-y-1 text-xs">
          {events.map((event) => (
            <li key={event.id} className="flex gap-3">
              <span className="w-40 shrink-0 text-fg-subtle">{formatDateTime(event.occurred_at)}</span>
              <span className="w-32 shrink-0 font-medium text-fg">{event.kind.replaceAll("_", " ")}</span>
              <span className="text-fg-muted">{event.message}</span>
            </li>
          ))}
        </ol>
      </div>
      {results.length ? (
        <DefinitionList
          items={results.map((result) => [
            `Response, page ${result.page}`,
            <span key={result.id} className="break-all text-xs">
              {result.content_type}, {result.raw_size} bytes, SHA-256 {result.raw_sha256}
              {result.from_cache ? " (reused)" : ""}
              {result.normalization_error ? " — could not be normalised; kept for inspection" : ""}
            </span>,
          ])}
        />
      ) : null}
      {evidence.data?.items.length ? (
        <div>
          <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-fg-subtle">Evidence</h3>
          <ul className="space-y-1 text-sm">
            {evidence.data.items.map((item) => {
              const related = (item.normalized.related as Array<{ type: string; value: string; relation: string }> | undefined) ?? [];
              return (
                <li key={item.id} className="flex flex-wrap items-center gap-2">
                  <Link to={`/search/evidence/${item.id}`} className="text-accent hover:underline">
                    {item.observation_kind}
                  </Link>
                  {item.is_simulated ? <Badge tone="warn">Simulated</Badge> : null}
                  {related.map((entry) => (
                    <span key={`${entry.type}:${entry.value}`} className="text-xs text-fg-muted">
                      {entry.relation.replaceAll("_", " ")} {entry.value}
                    </span>
                  ))}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
