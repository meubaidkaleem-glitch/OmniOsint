import { Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import {
  useAddScopeRule,
  useCheckScope,
  useCreateScope,
  useRemoveScopeRule,
  useRevokeScope,
  useScope,
  useScopes,
} from "@/api/queries";
import type { ScopeRuleIn } from "@/api/types";
import { useCan } from "@/app/context";
import { Button, IconButton } from "@/components/ui/button";
import { EmptyState, ErrorState, FormError, Notice } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/form";
import { Dialog } from "@/components/ui/overlay";
import { Badge, DefinitionList, Panel, Skeleton } from "@/components/ui/surface";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { SCOPE_MODES, SCOPE_STATUS, statusOf } from "@/lib/collection";
import { formatDateTime } from "@/lib/format";

const RULE_KINDS: Array<{ value: ScopeRuleIn["kind"]; label: string; example: string }> = [
  { value: "cidr", label: "Network (CIDR)", example: "198.51.100.0/24" },
  { value: "ip", label: "IP address", example: "198.51.100.7" },
  { value: "domain", label: "Domain (exact)", example: "app.example.com" },
  { value: "wildcard", label: "Subdomains", example: "*.example.com" },
  { value: "url_prefix", label: "URL prefix", example: "https://example.com/app/" },
];

/** "cidr 198.51.100.0/24" or "!ip 198.51.100.66" (exclusion), one per line. */
export function parseRules(text: string): ScopeRuleIn[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const exclusion = line.startsWith("!");
      const [kind = "", ...rest] = line.replace(/^!/, "").trim().split(/\s+/);
      return {
        kind: kind as ScopeRuleIn["kind"],
        value: rest.join(" "),
        is_exclusion: exclusion,
      };
    });
}

export function ScopesPage() {
  const can = useCan();
  const scopes = useScopes();
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  return (
    <div className="space-y-5">
      <Notice tone="info" title="Scopes record written authorisation">
        Passive lookups need no scope. Anything that contacts a target runs only inside an approved,
        unrevoked scope that is valid at that moment, covers the whole target and excludes none of it.
        Recording a scope is your statement that the authorisation exists.
      </Notice>
      <Panel
        title="Scopes"
        bodyClassName="p-0"
        actions={
          can("scopes:manage") ? (
            <Button size="sm" variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>
              Record a scope
            </Button>
          ) : null
        }
      >
        {scopes.isPending ? (
          <Skeleton className="m-4 h-24" />
        ) : scopes.isError ? (
          <ErrorState error={scopes.error} />
        ) : !scopes.data.items.length ? (
          <div className="p-4">
            <EmptyState title="No scope recorded">Active operations stay blocked until one is.</EmptyState>
          </div>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Name</TH>
                <TH>Mode</TH>
                <TH>Status</TH>
                <TH>Authorised by</TH>
                <TH>Valid until</TH>
              </TR>
            </THead>
            <TBody>
              {scopes.data.items.map((scope) => {
                const status = statusOf(SCOPE_STATUS, scope.status);
                return (
                  <TR key={scope.id} className="cursor-pointer" onClick={() => setSelected(scope.id)}>
                    <TD>
                      <button type="button" className="text-accent hover:underline">
                        {scope.name}
                      </button>
                    </TD>
                    <TD className="text-fg-muted">{SCOPE_MODES[scope.mode] ?? scope.mode}</TD>
                    <TD>
                      <Badge tone={status.tone}>{status.label}</Badge>
                    </TD>
                    <TD className="text-fg-muted">{scope.authorized_by}</TD>
                    <TD className="whitespace-nowrap text-fg-muted">{formatDateTime(scope.valid_until)}</TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </Panel>
      {selected ? <ScopeDetail id={selected} /> : null}
      {creating ? (
        <CreateScopeDialog
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            setSelected(id);
          }}
        />
      ) : null}
    </div>
  );
}

function ScopeDetail({ id }: { id: string }) {
  const can = useCan();
  const detail = useScope(id);
  const addRule = useAddScopeRule();
  const removeRule = useRemoveScopeRule();
  const revoke = useRevokeScope();
  const check = useCheckScope();
  const [kind, setKind] = useState<ScopeRuleIn["kind"]>("cidr");
  const [value, setValue] = useState("");
  const [exclusion, setExclusion] = useState(false);
  const [target, setTarget] = useState("");
  const [operation, setOperation] = useState<"discovery" | "assessment">("discovery");
  const [reason, setReason] = useState("");

  if (detail.isPending) return <Skeleton className="h-40" />;
  if (detail.isError) return <ErrorState error={detail.error} />;
  const { scope, rules } = detail.data;
  const open = scope.status !== "revoked";
  const manage = can("scopes:manage") && open;

  return (
    <Panel title={scope.name} description={SCOPE_MODES[scope.mode] ?? scope.mode} bodyClassName="space-y-5">
      <DefinitionList
        items={[
          ["Authorised by", scope.authorized_by],
          ["Reference", scope.authorization_reference ?? "-"],
          ["Valid", `${formatDateTime(scope.valid_from)} to ${formatDateTime(scope.valid_until)}`],
          ["Recorded", formatDateTime(scope.created_at)],
          ...(scope.revoked_at
            ? [["Revoked", `${formatDateTime(scope.revoked_at)}: ${scope.revoke_reason ?? ""}`] as [string, string]]
            : []),
        ]}
      />
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-subtle">Targets and exclusions</h3>
        <ul className="space-y-1 text-sm">
          {rules.map((rule) => (
            <li key={rule.id} className="flex items-center gap-2">
              <Badge tone={rule.is_exclusion ? "danger" : "ok"}>{rule.is_exclusion ? "Excluded" : "Included"}</Badge>
              <span className="text-fg-muted">{rule.kind.replace("_", " ")}</span>
              <code>{rule.value}</code>
              {manage ? (
                <IconButton
                  label={`Remove ${rule.value}`}
                  onClick={() => removeRule.mutate({ id: scope.id, ruleId: rule.id })}
                >
                  <Trash2 className="size-3.5" />
                </IconButton>
              ) : null}
            </li>
          ))}
        </ul>
        {manage ? (
          <form
            className="mt-3 flex flex-wrap items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              addRule.mutate(
                { id: scope.id, rule: { kind, value, is_exclusion: exclusion } },
                { onSuccess: () => setValue("") },
              );
            }}
          >
            <Select aria-label="Rule kind" className="h-8 w-44" value={kind} onChange={(event) => setKind(event.target.value as ScopeRuleIn["kind"])}>
              {RULE_KINDS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </Select>
            <Input
              aria-label="Rule value"
              className="h-8 w-64"
              placeholder={RULE_KINDS.find((item) => item.value === kind)?.example}
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
            <Checkbox label="Exclusion" checked={exclusion} onChange={(event) => setExclusion(event.target.checked)} />
            <Button size="sm" type="submit" disabled={!value.trim()} loading={addRule.isPending}>
              Add
            </Button>
          </form>
        ) : null}
        <FormError error={addRule.error ?? removeRule.error} />
      </div>
      <form
        className="space-y-2"
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          check.mutate({ id: scope.id, input: target, operation });
        }}
      >
        <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-subtle">Check a target</h3>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="Target to check"
            className="h-8 w-64"
            placeholder="198.51.100.7"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
          />
          <Select aria-label="Operation" className="h-8 w-40" value={operation} onChange={(event) => setOperation(event.target.value as "discovery" | "assessment")}>
            <option value="discovery">Discovery</option>
            <option value="assessment">Assessment</option>
          </Select>
          <Button size="sm" type="submit" disabled={!target.trim()} loading={check.isPending}>
            Check
          </Button>
        </div>
        <FormError error={check.error} />
        {check.data ? (
          <Notice tone={check.data.allowed ? "info" : "warn"} title={check.data.allowed ? "Allowed" : "Not allowed"}>
            {check.data.reason}
          </Notice>
        ) : null}
      </form>
      {manage ? (
        <form
          className="flex flex-wrap items-end gap-2 border-t border-line pt-4"
          onSubmit={(event) => {
            event.preventDefault();
            revoke.mutate({ id: scope.id, reason });
          }}
        >
          <Input
            aria-label="Reason for revoking"
            className="h-8 w-72"
            placeholder="Reason for revoking"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          <Button size="sm" variant="danger" type="submit" disabled={reason.trim().length < 3} loading={revoke.isPending}>
            Revoke scope
          </Button>
          <FormError error={revoke.error} />
        </form>
      ) : null}
    </Panel>
  );
}

function defaultUntil(): string {
  const date = new Date(Date.now() + 30 * 24 * 3600 * 1000);
  return date.toISOString().slice(0, 10);
}

function CreateScopeDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const create = useCreateScope();
  const [name, setName] = useState("");
  const [mode, setMode] = useState("authorized_discovery");
  const [authorizedBy, setAuthorizedBy] = useState("");
  const [reference, setReference] = useState("");
  const [until, setUntil] = useState(defaultUntil);
  const [rules, setRules] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(
      {
        name,
        mode: mode as "authorized_discovery",
        authorized_by: authorizedBy,
        authorization_reference: reference || null,
        valid_until: new Date(`${until}T23:59:59Z`).toISOString(),
        authorization_confirmed: confirmed,
        rules: parseRules(rules),
      },
      { onSuccess: (detail) => onCreated(detail.scope.id) },
    );
  }

  return (
    <Dialog open onOpenChange={(value) => (value ? null : onClose())} title="Record a scope">
      <form onSubmit={submit} className="space-y-3">
        <Field label="Name">{(props) => <Input {...props} value={name} onChange={(event) => setName(event.target.value)} />}</Field>
        <Field label="Mode">
          {(props) => (
            <Select {...props} value={mode} onChange={(event) => setMode(event.target.value)}>
              <option value="authorized_discovery">{SCOPE_MODES.authorized_discovery}</option>
              <option value="active_assessment">{SCOPE_MODES.active_assessment}</option>
            </Select>
          )}
        </Field>
        <Field label="Authorised by" hint="Who gave the written authorisation.">
          {(props) => <Input {...props} value={authorizedBy} onChange={(event) => setAuthorizedBy(event.target.value)} />}
        </Field>
        <Field label="Reference" optional hint="Contract, letter or ticket that grants it.">
          {(props) => <Input {...props} value={reference} onChange={(event) => setReference(event.target.value)} />}
        </Field>
        <Field label="Valid until">{(props) => <Input {...props} type="date" value={until} onChange={(event) => setUntil(event.target.value)} />}</Field>
        <Field label="Targets" hint="One per line: cidr 198.51.100.0/24, ip, domain, wildcard *.example.com or url_prefix. Start a line with ! to exclude.">
          {(props) => (
            <textarea
              {...props}
              rows={4}
              className="w-full rounded-md border border-line-strong bg-surface-2 px-3 py-2 font-mono text-xs text-fg"
              value={rules}
              onChange={(event) => setRules(event.target.value)}
            />
          )}
        </Field>
        <Checkbox
          label="Written authorisation exists for every target listed"
          description="Required. This statement is recorded in the audit trail with your name."
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        <FormError error={create.error} fields={["name", "authorized_by", "valid_until", "rules", "value", "authorization_confirmed"]} />
        <div className="flex justify-end gap-2 pt-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={create.isPending} disabled={!confirmed}>
            Record scope
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
