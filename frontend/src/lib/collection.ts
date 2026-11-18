/** Labels and tones for plan steps, jobs and requests. */
import { useCallback, useEffect, useState } from "react";

import { useInputTypes } from "@/api/queries";

export type Tone = "neutral" | "accent" | "ok" | "warn" | "danger";

export const STEP_STATUS: Record<string, { label: string; tone: Tone }> = {
  ready: { label: "Will run", tone: "ok" },
  cached: { label: "Cached result", tone: "accent" },
  needs_approval: { label: "Needs approval", tone: "warn" },
  blocked: { label: "Blocked", tone: "danger" },
  skipped: { label: "Not chosen", tone: "neutral" },
  unavailable: { label: "Unavailable", tone: "neutral" },
  planned: { label: "Planned", tone: "neutral" },
  excluded: { label: "Excluded", tone: "neutral" },
};

export const JOB_STATUS: Record<string, { label: string; tone: Tone }> = {
  queued: { label: "Queued", tone: "accent" },
  awaiting_approval: { label: "Awaiting approval", tone: "warn" },
  running: { label: "Running", tone: "accent" },
  succeeded: { label: "Succeeded", tone: "ok" },
  failed: { label: "Failed", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  skipped: { label: "Skipped", tone: "neutral" },
};

export const REQUEST_STATUS: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "Pending", tone: "accent" },
  awaiting_approval: { label: "Awaiting approval", tone: "warn" },
  running: { label: "Running", tone: "accent" },
  completed: { label: "Completed", tone: "ok" },
  partial: { label: "Partly failed", tone: "warn" },
  failed: { label: "Failed", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export const RANK_TONE: Record<string, Tone> = { strong: "ok", plausible: "accent", weak: "neutral" };

export const SCOPE_STATUS: Record<string, { label: string; tone: Tone }> = {
  active: { label: "Active", tone: "ok" },
  not_approved: { label: "Not approved", tone: "warn" },
  not_yet_valid: { label: "Not valid yet", tone: "warn" },
  expired: { label: "Expired", tone: "neutral" },
  revoked: { label: "Revoked", tone: "danger" },
};

export const SCOPE_MODES: Record<string, string> = {
  passive: "Passive (no active operations)",
  authorized_discovery: "Authorised discovery",
  active_assessment: "Active assessment",
};

/** Failure modes of the simulated provider, for testing the pipeline. */
export const SIMULATION_MODES: Array<{ value: string; label: string }> = [
  { value: "", label: "Normal response" },
  { value: "timeout", label: "Timeout" },
  { value: "unavailable", label: "Outage (HTTP 503)" },
  { value: "rate_limited", label: "Rate limited (HTTP 429)" },
  { value: "quota", label: "Quota used up" },
  { value: "auth", label: "Credentials refused (HTTP 401)" },
  { value: "malformed", label: "Malformed response" },
  { value: "empty", label: "Empty result" },
  { value: "partial", label: "Partial result (page 2 fails)" },
  { value: "flaky", label: "Fails once, then succeeds" },
];

export function statusOf(
  table: Record<string, { label: string; tone: Tone }>,
  status: string,
): { label: string; tone: Tone } {
  return table[status] ?? { label: status.replaceAll("_", " "), tone: "neutral" };
}

/** ``value`` after it has stopped changing for ``delay`` milliseconds. */
export function useDebouncedValue<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

/** "1 observation", "3 observations". */
export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** The display name of an input type ("IPv4 address"), from the server's list of types. */
export function useTypeLabel(): (type: string) => string {
  const types = useInputTypes();
  return useCallback(
    (type: string) => types.data?.items.find((item) => item.type === type)?.label ?? type.replaceAll("_", " "),
    [types.data],
  );
}
