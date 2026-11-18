import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { CandidateOut, ClassificationOut, JobOut, PlanOut, RequestDetailOut } from "@/api/types";
import { parseRules } from "@/pages/admin/ScopesPage";
import { authState, shellHandlers } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/utils";

const NOW = "2026-11-18T10:00:00Z";
const PLANNED = "Planned — integration not yet implemented.";

function candidate(overrides: Partial<CandidateOut>): CandidateOut {
  return {
    type: "domain",
    label: "Domain",
    value: "example.org",
    display: "example.org",
    rank: "strong",
    reason: "A registrable domain name.",
    notes: [],
    details: {},
    entity_type: "domain",
    modules: ["domain"],
    ...overrides,
  };
}

function classification(overrides: Partial<ClassificationOut> = {}): ClassificationOut {
  return {
    input: "example.org",
    status: "recognized",
    message: "Recognised as a domain.",
    candidates: [candidate({})],
    mentions: [],
    refanged: false,
    hints: [],
    ...overrides,
  };
}

function plan(overrides: Partial<PlanOut> = {}): PlanOut {
  return {
    indicator: { type: "domain", label: "Domain", value: "example.org", display: "example.org", entity_type: "domain" },
    mode: "passive",
    strategy: "free_first",
    providers: null,
    scope: null,
    force_refresh: false,
    modules: [{ id: "domain", title: "Domain intelligence", phase: 4 }],
    steps: [
      {
        provider_id: "simulated",
        provider_name: "Simulated provider",
        capability_id: "simulated.lookup",
        capability_name: "Simulated lookup",
        description: null,
        operation: "lookup",
        active: false,
        cost: { kind: "free" },
        simulated: true,
        status: "ready",
        message: "Will be collected.",
        selected: true,
        phase: null,
        cached_result_id: null,
        cache_fresh_until: null,
        scope_decision: null,
      },
      {
        provider_id: "securitytrails",
        provider_name: "SecurityTrails",
        capability_id: null,
        capability_name: null,
        description: null,
        operation: null,
        active: false,
        cost: { kind: "unknown" },
        simulated: false,
        status: "planned",
        message: PLANNED,
        selected: false,
        phase: 4,
        cached_result_id: null,
        cache_fresh_until: null,
        scope_decision: null,
      },
    ],
    summary: { ready: 1, planned: 1, selected: 1 },
    warnings: ["The simulated provider is enabled."],
    ...overrides,
  };
}

function job(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "00000000-0000-7000-8000-0000000000j1",
    request_id: "00000000-0000-7000-8000-0000000000r1",
    indicator_type: "ipv4",
    indicator_value: "198.51.100.7",
    provider_id: "simulated",
    capability: "simulated.probe",
    is_active: true,
    is_simulated: true,
    scope_id: "00000000-0000-7000-8000-0000000000s1",
    status: "awaiting_approval",
    attempt: 0,
    max_attempts: 3,
    scheduled_at: NOW,
    started_at: null,
    finished_at: null,
    cancel_requested_at: null,
    progress: {},
    error: null,
    outcome: null,
    cost: { kind: "free" },
    approved_at: null,
    created_at: NOW,
    ...overrides,
  };
}

function requestDetail(jobs: JobOut[]): RequestDetailOut {
  return {
    request: {
      id: "00000000-0000-7000-8000-0000000000r1",
      input_text: "198.51.100.7",
      indicator_type: "ipv4",
      indicator_value: "198.51.100.7",
      entity_id: null,
      mode: "active",
      strategy: "free_first",
      scope_id: "00000000-0000-7000-8000-0000000000s1",
      status: "awaiting_approval",
      is_simulated: true,
      created_by: null,
      created_at: NOW,
      finished_at: null,
    },
    plan: { steps: [] },
    jobs,
  };
}

const SIDE = {
  "GET /search/history": { body: { items: [] } },
  "GET /search/saved": { body: { items: [] } },
};

describe("universal search", () => {
  it("classifies, previews the plan and runs it", async () => {
    const { calls } = mockApi({
      ...shellHandlers(),
      ...SIDE,
      "POST /search/classify": { body: classification() },
      "POST /collection/plan": { body: plan() },
      "POST /collection/requests": { status: 201, body: requestDetail([]).request },
      "GET /collection/requests/00000000-0000-7000-8000-0000000000r1": { body: requestDetail([]) },
    });
    const { router } = renderApp("/search?q=example.org");
    expect(await screen.findByText("Recognised as a domain.")).toBeInTheDocument();
    expect(await screen.findByText("Simulated lookup")).toBeInTheDocument();
    expect(screen.getByText((text) => text.startsWith(PLANNED) && text.includes("Phase 4"))).toBeInTheDocument();
    expect(screen.getByText("The simulated provider is enabled.")).toBeInTheDocument();
    const planCall = calls.find((call) => call.path === "/collection/plan");
    expect(planCall?.body).toMatchObject({ input: "example.org", type: "domain", mode: "passive" });
    await userEvent.click(screen.getByRole("button", { name: /Run 1 step/ }));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/search/requests/00000000-0000-7000-8000-0000000000r1"),
    );
  });

  it("asks for a choice when the input is ambiguous", async () => {
    const { calls } = mockApi({
      ...shellHandlers(),
      ...SIDE,
      "POST /search/classify": {
        body: classification({
          input: "da39a3ee5e6b4b0d3255bfef95601890afd80709",
          status: "ambiguous",
          message: "This input can be read in 2 ways. Choose the one you mean.",
          candidates: [
            candidate({ type: "certificate_fingerprint", label: "Certificate fingerprint", rank: "plausible" }),
            candidate({ type: "file_hash", label: "File hash", rank: "plausible" }),
          ],
        }),
      },
      "POST /collection/plan": { body: plan() },
    });
    renderApp("/search?q=da39a3ee5e6b4b0d3255bfef95601890afd80709");
    expect(await screen.findByText(/Choose the reading you mean/)).toBeInTheDocument();
    expect(calls.some((call) => call.path === "/collection/plan")).toBe(false);
    await userEvent.click(screen.getByRole("radio", { name: /File hash/ }));
    await waitFor(() =>
      expect(calls.find((call) => call.path === "/collection/plan")?.body).toMatchObject({ type: "file_hash" }),
    );
  });

  it("offers no run button without the collection:run permission", async () => {
    mockApi({
      ...shellHandlers(authState({ permissions: ["collection:read"], user: { roles: ["auditor"] } })),
      ...SIDE,
      "POST /search/classify": { body: classification() },
      "POST /collection/plan": { body: plan() },
    });
    renderApp("/search?q=example.org");
    const run = await screen.findByRole("button", { name: /Run 1 step/ });
    expect(run).toBeDisabled();
  });
});

describe("collection requests", () => {
  it("shows an active job waiting for approval and approves it", async () => {
    const waiting = job();
    const { calls } = mockApi({
      ...shellHandlers(),
      "GET /collection/requests/00000000-0000-7000-8000-0000000000r1": { body: requestDetail([waiting]) },
      "GET /collection/jobs/00000000-0000-7000-8000-0000000000j1": {
        body: {
          job: waiting,
          events: [
            { id: "e1", occurred_at: NOW, kind: "created", message: "Active operation allowed by the scope; it waits for approval.", details: {} },
          ],
          results: [],
          evidence_count: 0,
        },
      },
      "GET /evidence": { body: { items: [], next_cursor: null } },
      "POST /collection/jobs/00000000-0000-7000-8000-0000000000j1/approve": {
        body: job({ status: "queued" }),
      },
    });
    renderApp("/search/requests/00000000-0000-7000-8000-0000000000r1");
    expect(await screen.findByText(/Everything collected for this request came from the simulated provider/)).toBeInTheDocument();
    const row = screen.getByText("simulated.probe").closest("tr");
    expect(within(row as HTMLElement).getByText("Active")).toBeInTheDocument();
    await userEvent.click(row as HTMLElement);
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(calls.some((call) => call.method === "POST" && call.path.endsWith("/approve"))).toBe(true),
    );
  });

  it("shows the real reason a job failed", async () => {
    const failed = job({
      is_active: false,
      capability: "simulated.lookup",
      status: "failed",
      attempt: 1,
      error: { code: "provider_quota_exceeded", message: "Simulated quota exhaustion.", retryable: false },
    });
    mockApi({
      ...shellHandlers(),
      "GET /collection/requests/00000000-0000-7000-8000-0000000000r1": { body: requestDetail([failed]) },
    });
    renderApp("/search/requests/00000000-0000-7000-8000-0000000000r1");
    expect(await screen.findByText("Simulated quota exhaustion.")).toBeInTheDocument();
  });
});

describe("scopes", () => {
  it("parses rules with exclusions", () => {
    expect(parseRules("cidr 198.51.100.0/24\n\n!ip 198.51.100.66\n")).toEqual([
      { kind: "cidr", value: "198.51.100.0/24", is_exclusion: false },
      { kind: "ip", value: "198.51.100.66", is_exclusion: true },
    ]);
  });

  it("will not record a scope without the authorisation statement", async () => {
    mockApi({ ...shellHandlers(), "GET /scopes": { body: { items: [] } } });
    renderApp("/admin/scopes");
    await userEvent.click(await screen.findByRole("button", { name: /Record a scope/ }));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Record scope" });
    expect(submit).toBeDisabled();
    await userEvent.click(within(dialog).getByLabelText(/Written authorisation exists/));
    expect(submit).toBeEnabled();
  });
});
