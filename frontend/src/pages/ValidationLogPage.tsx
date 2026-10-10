// Validation log (owner, qc): every write a business rule refused, newest first (migration 018). The refused change
// itself was rolled back; this row is written separately so the attempt is never lost.
import { Lock } from "lucide-react";
import { api } from "@/api/client";
import type { ValidationLogRow } from "@/api/types";
import { Badge, Card, DataTable, EmptyState, Field, Input, ListToolbar, Loadable, PageHeader, Pager, type Column } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useListQuery } from "@/hooks/useListQuery";
import { usePermissions } from "@/hooks/usePermissions";
import { formatDateTime, humanize } from "@/lib/format";

const CODES = ["PHASE_SKIPPED", "LOT_QUARANTINED", "INSUFFICIENT_STOCK", "NOT_QC_PASSED", "NOT_IN_ORDER", "SHADE_MISMATCH",
  "OVERPAYMENT", "ORDER_CLOSED", "ATTENDANCE_FUTURE_DATE", "WORKER_INACTIVE", "LAST_OWNER", "SELF_DEACTIVATION"];

export default function ValidationLogPage() {
  const { can, loading } = usePermissions();
  if (loading) return null;
  if (!can("validation_log.view"))
    return (
      <Card>
        <EmptyState title="The validation log is for the owner and QC" body="Sign in as owner@ or qc@." action={<Lock className="size-5 text-muted" aria-hidden />} />
      </Card>
    );
  return <LogList />;
}

function summary(v: unknown): string {
  if (v == null) return "—";
  const s = JSON.stringify(v);
  return s.length > 80 ? `${s.slice(0, 80)}…` : s;
}

function LogList() {
  const list = useListQuery(["page", "q", "sort", "code", "user", "since", "before"]);
  const log = useApi(() => api.validationLog.list(list.query), [list.signature]);
  const columns: Column<ValidationLogRow>[] = [
    { key: "at", header: "When", sortKey: "at", render: (r) => <span className="whitespace-nowrap">{formatDateTime(r.at)}</span> },
    { key: "error_code", header: "Rule", sortKey: "error_code", render: (r) => (
      <span className="grid gap-0.5">
        <Badge tone={r.error_code === "PHASE_SKIPPED" ? "warn" : "bad"}>{humanize(r.error_code.toLowerCase())}</Badge>
        {r.sqlstate && <span className="font-mono text-xs text-muted">{r.sqlstate}</span>}
      </span>
    ) },
    { key: "message", header: "Why", render: (r) => <span className="text-ink">{r.message}</span> },
    { key: "user_email", header: "Who", sortKey: "user_email", render: (r) => (r.user_email ? <span className="font-mono text-xs">{r.user_email}</span> : "—") },
    { key: "path", header: "Action", sortKey: "path", render: (r) => <span className="whitespace-nowrap font-mono text-xs">{r.method} {r.path}</span> },
    { key: "input_summary", header: "Input", render: (r) => <span className="font-mono text-xs text-muted">{summary(r.input_summary)}</span> },
  ];
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <PageHeader title="Validation log" subtitle="Every change a business rule refused: what was tried, by whom, and why. The change itself was not saved." />
      <Card padded={false}>
        <div className="grid gap-3 border-b border-line p-4">
          <ListToolbar
            q={list.query.q ?? ""}
            onSearch={(q) => list.set("q", q)}
            placeholder="Search message, roll code, user"
            filters={[{ key: "code", label: "Rule", options: CODES.map((c) => ({ value: c, label: humanize(c.toLowerCase()) })) }]}
            values={list.query}
            onFilter={(k, v) => list.set(k, v)}
          />
          <div className="flex flex-wrap gap-3">
            <Field label="From">
              <Input type="date" value={list.query.since?.slice(0, 10) ?? ""} onChange={(e) => list.set("since", e.target.value || undefined)} />
            </Field>
            <Field label="Before">
              <Input type="date" value={list.query.before?.slice(0, 10) ?? ""} onChange={(e) => list.set("before", e.target.value || undefined)} />
            </Field>
            <Field label="User email">
              <Input value={list.query.user ?? ""} onChange={(e) => list.set("user", e.target.value || undefined)} placeholder="qc@everest.test" />
            </Field>
          </div>
        </div>
        <Loadable state={log}>
          {(page) => (
            <>
              <DataTable columns={columns} rows={page.items} rowKey={(r) => String(r.id)} sort={list.query.sort} onSort={(s) => list.set("sort", s)}
                emptyText="Nothing refused yet. Try inspecting a greige roll by code on the Quality page." />
              <div className="border-t border-line p-4">
                <Pager page={page.page} pageSize={page.page_size} total={page.total} onPage={(p) => list.set("page", String(p))} />
              </div>
            </>
          )}
        </Loadable>
      </Card>
    </div>
  );
}
