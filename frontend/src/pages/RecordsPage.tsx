// Records: every list in the mill, paged on the server (?page=&page_size=&q=&sort=&<filters>), state in the URL.
// For evaluators and for the office. The demo pages (Floor, Quality, Orders…) are unchanged.
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import type { InvoiceRow, ListQuery, OrderSummary, Page, QualityQueueItem, Rejection, RollListItem, StockRow, WorkerRow } from "@/api/types";
import { Badge, Card, DataTable, ListToolbar, Loadable, PageHeader, Pager, type Column, type FilterDef } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useListQuery } from "@/hooks/useListQuery";
import { usePermissions } from "@/hooks/usePermissions";
import { formatDate, formatDateTime, formatINR, formatQty, humanize } from "@/lib/format";
import { custodyLabel, custodyTone } from "@/lib/tones";

type Tab<T> = {
  key: string;
  label: string;
  load: (q: ListQuery) => Promise<Page<T>>;
  columns: Column<T>[];
  rowKey: (row: T) => string;
  filters: FilterDef[];
  search: string;
  permission?: string; // needed to open it (017); undefined = everyone signed in
};
const tab = <T,>(t: Tab<T>) => t as unknown as Tab<Record<string, unknown>>;

const opts = (values: string[]) => values.map((v) => ({ value: v, label: humanize(v) }));
const yesNo = [
  { value: "true", label: "Yes" },
  { value: "false", label: "No" },
];
const rollLink = (code: string) => (
  <Link to={`/roll/${encodeURIComponent(code)}`} className="whitespace-nowrap font-mono text-brand underline">
    {code}
  </Link>
);
const mono = (v: string | null) => (v ? <span className="whitespace-nowrap font-mono">{v}</span> : "—");

const TABS = [
  tab<RollListItem>({
    key: "rolls", label: "Rolls", load: api.lists.rolls, rowKey: (r) => r.code, search: "Search roll, order, buyer, product",
    filters: [
      { key: "custody", label: "Where", options: Object.entries(custodyLabel).filter(([k]) => k !== "consumed").map(([value, label]) => ({ value, label })) },
      { key: "kind", label: "Kind", options: opts(["greige", "finished"]) },
      { key: "qc_result", label: "Latest QC", options: opts(["pass", "rework", "reject"]) },
      { key: "status", label: "Status", options: opts(["active", "wip", "dispatched", "quarantined", "recalled"]) },
    ],
    columns: [
      { key: "code", header: "Roll", sortKey: "code", render: (r) => rollLink(r.code) },
      { key: "product", header: "Product" },
      { key: "qty_m", header: "Metres", align: "right", sortKey: "qty_m", render: (r) => formatQty(r.qty_m, "m") },
      { key: "custody", header: "Where", sortKey: "custody", render: (r) => <Badge tone={custodyTone[r.custody]}>{custodyLabel[r.custody]}</Badge> },
      { key: "qc_result", header: "QC", render: (r) => (r.qc_result ? `${humanize(r.qc_result)}${r.defect_type ? ` · ${humanize(r.defect_type)}` : ""}` : "—") },
      { key: "order_code", header: "Order", sortKey: "order_code", render: (r) => mono(r.order_code) },
      { key: "buyer", header: "Buyer", render: (r) => r.buyer ?? "—" },
    ],
  }),
  tab<OrderSummary>({
    key: "orders", label: "Orders", load: api.lists.orders, rowKey: (o) => o.code, search: "Search order, buyer, product",
    filters: [
      { key: "status", label: "Status", options: opts(["confirmed", "in_production", "partially_dispatched", "dispatched", "cancelled"]) },
      { key: "yarn_status", label: "Yarn", options: opts(["ok", "short"]) },
      { key: "late", label: "Late", options: yesNo },
    ],
    columns: [
      { key: "code", header: "Order", sortKey: "code", render: (o) => mono(o.code) },
      { key: "buyer", header: "Buyer", sortKey: "buyer" },
      { key: "product", header: "Product" },
      { key: "ordered_m", header: "Ordered", align: "right", sortKey: "ordered_m", render: (o) => formatQty(o.ordered_m, "m") },
      { key: "status", header: "Status", sortKey: "status", render: (o) => humanize(o.status) },
      { key: "promised_date", header: "Promised", sortKey: "promised_date", render: (o) => formatDate(o.promised_date) },
      { key: "delay_days", header: "Delay", align: "right", sortKey: "delay_days", render: (o) => (o.delay_days ? `+${o.delay_days}` : "—") },
    ],
  }),
  tab<StockRow>({
    key: "stock", label: "Stock", load: api.lists.stock, rowKey: (r) => `${r.location_code}:${r.lot_code}`, search: "Search lot, product, location",
    filters: [
      { key: "lot_kind", label: "Kind", options: opts(["yarn", "greige", "finished"]) },
      { key: "location_code", label: "Location", options: ["YARN-STORE", "GREIGE-STORE", "FG-STORE", "REJECT-BAY", "QUARANTINE"].map((v) => ({ value: v, label: v })) },
    ],
    columns: [
      { key: "location_code", header: "Location", sortKey: "location_code", render: (r) => mono(r.location_code) },
      { key: "lot_code", header: "Lot", sortKey: "lot_code", render: (r) => (r.lot_kind === "yarn" ? mono(r.lot_code) : rollLink(r.lot_code)) },
      { key: "product_code", header: "Product", sortKey: "product_code", render: (r) => mono(r.product_code) },
      { key: "qty", header: "On hand", align: "right", sortKey: "qty", render: (r) => formatQty(r.qty, r.uom) },
    ],
  }),
  tab<QualityQueueItem>({
    key: "qc", label: "QC queue", load: api.lists.qcQueue, rowKey: (r) => r.lot_code, search: "Search roll, order, batch",
    filters: [],
    columns: [
      { key: "lot_code", header: "Roll", sortKey: "lot_code", render: (r) => rollLink(r.lot_code) },
      { key: "product", header: "Product" },
      { key: "dye_batch", header: "Batch", sortKey: "dye_batch", render: (r) => mono(r.dye_batch) },
      { key: "dyed_at", header: "Dyed", sortKey: "dyed_at", render: (r) => formatDateTime(r.dyed_at) },
      { key: "order_code", header: "Order", sortKey: "order_code", render: (r) => mono(r.order_code) },
    ],
  }),
  tab<Rejection>({
    key: "rejections", label: "Rejections", load: api.lists.rejections, rowKey: (r) => `${r.lot_code}:${r.inspected_at}`,
    search: "Search roll, order, inspector",
    filters: [{ key: "defect_type", label: "Defect", options: opts(["colour_mismatch", "missing_pick", "oil_stain", "hole", "uneven_weave", "other"]) }],
    columns: [
      { key: "lot_code", header: "Roll", sortKey: "lot_code", render: (r) => rollLink(r.lot_code) },
      { key: "defect_type", header: "Defect", sortKey: "defect_type", render: (r) => humanize(r.defect_type) },
      { key: "inspector", header: "Inspector", sortKey: "inspector" },
      { key: "inspected_at", header: "When", sortKey: "inspected_at", render: (r) => formatDateTime(r.inspected_at) },
      { key: "order_code", header: "Order", render: (r) => mono(r.order_code) },
    ],
  }),
  tab<InvoiceRow>({
    key: "invoices", label: "Invoices", load: api.lists.invoices, rowKey: (r) => r.code, search: "Search invoice, order, buyer",
    permission: "finance.access",
    filters: [{ key: "unpaid", label: "Outstanding", options: yesNo }],
    columns: [
      { key: "code", header: "Invoice", sortKey: "code", render: (r) => mono(r.code) },
      { key: "buyer", header: "Buyer", sortKey: "buyer" },
      { key: "dispatch_code", header: "Dispatch", render: (r) => <>{mono(r.dispatch_code)} · {r.rolls} rolls</> },
      { key: "issued_at", header: "Issued", sortKey: "issued_at", render: (r) => formatDate(r.issued_at) },
      { key: "amount", header: "Amount", align: "right", sortKey: "amount", render: (r) => formatINR(r.amount) },
      { key: "outstanding", header: "Outstanding", align: "right", sortKey: "outstanding", render: (r) => formatINR(r.outstanding) },
    ],
  }),
  tab<WorkerRow>({
    key: "workers", label: "Workers", load: api.lists.workers, rowKey: (r) => r.code, search: "Search code or name",
    permission: "workforce.register",
    filters: [
      { key: "skill", label: "Skill", options: opts(["weaving", "dyeing", "spinning", "finishing"]) },
      { key: "active", label: "Active", options: yesNo },
    ],
    columns: [
      { key: "code", header: "Code", sortKey: "code", render: (r) => mono(r.code) },
      { key: "full_name", header: "Name", sortKey: "full_name" },
      { key: "skill", header: "Skill", sortKey: "skill", render: (r) => humanize(r.skill) },
      { key: "hourly_wage", header: "₹/hour", align: "right", sortKey: "hourly_wage", render: (r) => formatINR(r.hourly_wage) },
      { key: "active", header: "Active", render: (r) => (r.active ? "Yes" : "No") },
    ],
  }),
];

export default function RecordsPage() {
  const { can } = usePermissions();
  const visible = TABS.filter((t) => !t.permission || can(t.permission));
  const [params, setParams] = useSearchParams();
  const current = visible.find((t) => t.key === params.get("tab")) ?? visible[0];

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <PageHeader title="Records" subtitle="Every roll, order, stock position and inspection: search, filter, sort, page." />
      <div role="tablist" aria-label="Lists" className="flex gap-1 overflow-x-auto border-b border-line">
        {visible.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={t.key === current.key}
            onClick={() => setParams({ tab: t.key }, { replace: true })}
            className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${t.key === current.key ? "border-brand text-brand" : "border-transparent text-muted hover:text-ink"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <RecordList key={current.key} tab={current} />
    </div>
  );
}

function RecordList({ tab: t }: { tab: Tab<Record<string, unknown>> }) {
  const list = useListQuery(["page", "page_size", "q", "sort", ...t.filters.map((f) => f.key)]);
  const data = useApi(() => t.load(list.query), [list.signature]);
  return (
    <Card padded={false}>
      <div className="border-b border-line p-4">
        <ListToolbar
          q={list.query.q ?? ""}
          onSearch={(q) => list.set("q", q)}
          filters={t.filters}
          values={list.query}
          onFilter={(k, v) => list.set(k, v)}
          placeholder={t.search}
        />
      </div>
      <Loadable state={data}>
        {(page) => (
          <>
            <DataTable
              columns={t.columns}
              rows={page.items}
              rowKey={t.rowKey}
              emptyText="Nothing matches. Clear the search or a filter."
              sort={list.query.sort}
              onSort={(s) => list.set("sort", s)}
            />
            <div className="border-t border-line p-4">
              <Pager page={page.page} pageSize={page.page_size} total={page.total} onPage={(p) => list.set("page", String(p))} />
            </div>
          </>
        )}
      </Loadable>
    </Card>
  );
}
