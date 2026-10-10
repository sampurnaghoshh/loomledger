// Close of the demo: the yarn mass balance to date (where every issued kilo went, and which loom loses it),
// the true cost of every roll on an order, and the month's profit & loss. Accounts and the owner only.
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Lock } from "lucide-react";
import { api } from "@/api/client";
import type { MassBalance, OrderSummary, Pnl, RollCost } from "@/api/types";
import { Badge, Card, DataTable, EmptyState, Field, Loadable, PageHeader, Select, StatTile, type Column } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { getSession } from "@/lib/auth";
import { formatDate, formatDateTime, formatINR, formatMonth, formatPct, formatQty, humanize } from "@/lib/format";
import { custodyLabel, custodyTone, lotStatusTone } from "@/lib/tones";

const ALLOWED_ROLES = ["owner", "accounts"];
const TO_DATE = "";            // period value for "everything so far" (the locked Close figure)
const MONTHS_BACK = 3;         // the current month and the two before it

export default function MonthEndPage() {
  const role = getSession()?.user.role;
  return (
    <div className="grid gap-6">
      <PageHeader title="Month-end" subtitle="Yarn mass balance, the true cost of every roll, and profit & loss" />
      {role && ALLOWED_ROLES.includes(role) ? <MonthEnd /> : <NotAllowed />}
    </div>
  );
}

function NotAllowed() {
  return (
    <Card>
      <EmptyState
        title="Month-end figures are for Accounts"
        body="Sign in as accounts@ or owner@ to see the mass balance, roll costs and profit & loss."
        action={<Lock className="size-5 text-muted" aria-hidden />}
      />
    </Card>
  );
}

/** "" (to date) or "YYYY-MM" → the API window. Months are [first day, first day of next month). */
function windowFor(period: string): { from?: string; to?: string } {
  if (period === TO_DATE) return {};
  const [y, m] = period.split("-").map(Number);
  const next = m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, "0")}`;
  return { from: `${period}-01`, to: `${next}-01` };
}

function recentMonths(): string[] {
  const parts = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", timeZone: "Asia/Kolkata" })
    .formatToParts(new Date());
  let y = Number(parts.find((p) => p.type === "year")?.value);
  let m = Number(parts.find((p) => p.type === "month")?.value);
  const out: string[] = [];
  for (let i = 0; i < MONTHS_BACK; i++) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    if (--m === 0) [y, m] = [y - 1, 12];
  }
  return out;
}

/** What the figures cover, from what the API answered (not from what was asked). */
function periodLabel(mb: MassBalance): string {
  if (mb.from == null && mb.to == null)
    return mb.first_run_at ? `Mass balance · to date (since ${formatDate(mb.first_run_at)})` : "Mass balance · to date";
  return `Mass balance · ${formatMonth(mb.from)}`;
}

function MonthEnd() {
  const months = useMemo(recentMonths, []);
  const [period, setPeriod] = useState(TO_DATE);
  const balance = useApi(() => {
    const w = windowFor(period);
    return api.finance.massBalance(w.from, w.to);
  }, [period]);

  return (
    <>
      <div className="max-w-xs">
        <Field label="Period">
          <Select value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value={TO_DATE}>To date (all runs so far)</option>
            {months.map((ym) => (
              <option key={ym} value={ym}>
                {formatMonth(ym)}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      <Loadable state={balance}>
        {(mb) =>
          mb.by_machine.length === 0 ? (
            <Card>
              <EmptyState title="No weaving runs in this period" body="Pick another period, or “To date” for everything so far." />
            </Card>
          ) : (
            <Balance mb={mb} />
          )
        }
      </Loadable>

      <RollCosts />

      <ProfitAndLoss months={months} />
    </>
  );
}

// ---------------------------------------------------------------- mass balance
function Balance({ mb }: { mb: MassBalance }) {
  const t = mb.totals;
  const worst = mb.by_machine[0];
  const leaking = mb.by_machine.filter((m) => m.unaccounted_kg > 0);

  let sentence: string;
  if (t.unaccounted_kg <= 0) sentence = "Every kilo of issued yarn is accounted for.";
  else if (leaking.length === 1)
    sentence = `All of the gap is on ${worst.machine_name}: ${formatQty(worst.unaccounted_kg, "kg")} unaccounted, ${formatPct(worst.unaccounted_pct)} of the yarn it was issued.`;
  else
    sentence = `${worst.machine_name} has the largest gap: ${formatQty(worst.unaccounted_kg, "kg")} of ${formatQty(t.unaccounted_kg, "kg")} unaccounted.`;

  return (
    <>
      <Card title={periodLabel(mb)} subtitle="Issued yarn = fabric woven + recorded waste + still on the looms + unaccounted · kg = m × width × GSM / 1000">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <StatTile label="Issued" value={formatQty(t.issued_kg, "kg")} tone="brand" />
          <StatTile label="Fabric woven" value={formatQty(t.fabric_kg, "kg")} />
          <StatTile label="Recorded waste" value={formatQty(t.waste_kg, "kg")} />
          <StatTile label="On the looms" value={formatQty(t.wip_kg, "kg")} />
          <div className="col-span-2 lg:col-span-1">
            <StatTile
              label="Unaccounted"
              value={formatQty(t.unaccounted_kg, "kg")}
              hint={`${formatPct(t.unaccounted_pct)} of issued`}
              tone={t.unaccounted_kg > 0 ? "bad" : "ok"}
            />
          </div>
        </div>
      </Card>

      <Card title="Unaccounted yarn by machine" subtitle={sentence}>
        <div
          style={{ height: `${mb.by_machine.length * 40 + 24}px` }}
          role="img"
          aria-label={`Bar chart of unaccounted yarn by machine. ${sentence}`}
        >
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={mb.by_machine} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid horizontal={false} className="stroke-line" />
              <XAxis type="number" tickLine={false} axisLine={false} tick={{ fontSize: 12 }} unit=" kg" />
              <YAxis type="category" dataKey="machine_name" tickLine={false} axisLine={false} width={64} tick={{ fontSize: 12 }} />
              <Tooltip
                cursor={{ className: "fill-idle-soft" }}
                formatter={(v) => [formatQty(Number(v), "kg"), "Unaccounted"]}
              />
              <Bar dataKey="unaccounted_kg" radius={[0, 4, 4, 0]} minPointSize={2} barSize={22}>
                {mb.by_machine.map((m) => (
                  <Cell key={m.machine_code} className={m.unaccounted_kg > 0 ? "fill-bad" : "fill-idle"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <ul className="mt-4 grid grid-cols-2 gap-2 text-sm sm:grid-cols-3 lg:grid-cols-6">
          {mb.by_machine.map((m) => (
            <li key={m.machine_code} className="rounded-lg border border-line px-3 py-2">
              <p className="font-medium text-ink">{m.machine_name}</p>
              <p className="num text-muted">
                {formatQty(m.issued_kg, "kg")} issued · {m.runs} runs
              </p>
              <p className={`num font-medium ${m.unaccounted_kg > 0 ? "text-bad" : "text-muted"}`}>
                {formatPct(m.unaccounted_pct)} unaccounted
              </p>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- true cost per roll
/** Default: the first order whose promise date slipped (the story's), else the first order. */
function defaultOrder(orders: OrderSummary[]): string {
  return (orders.find((o) => o.revised_promise_date) ?? orders[0])?.code ?? "";
}

function RollCosts() {
  const orders = useApi(() => api.orders.list(), []);
  const [chosen, setChosen] = useState<string | null>(null);
  const orderCode = chosen ?? (orders.data ? defaultOrder(orders.data) : "");

  return (
    <Card title="True cost per roll" subtitle="Yarn + machine time + labour + chemicals, rolled up each roll's family tree">
      <Loadable state={orders}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState title="No orders yet" />
          ) : (
            <div className="grid gap-4">
              <div className="max-w-xs">
                <Field label="Order">
                  <Select value={orderCode} onChange={(e) => setChosen(e.target.value)}>
                    {list.map((o) => (
                      <option key={o.code} value={o.code}>
                        {o.code} · {o.buyer}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              {orderCode && <CostTable orderCode={orderCode} />}
            </div>
          )
        }
      </Loadable>
    </Card>
  );
}

function CostTable({ orderCode }: { orderCode: string }) {
  const costs = useApi(() => api.finance.rollCosts(orderCode), [orderCode]);
  const columns: Column<RollCost>[] = [
    { key: "roll", header: "Roll", render: (r) => <span className="whitespace-nowrap font-mono font-medium">{r.lot_code}</span> },
    {
      key: "custody",
      header: "Where",
      render: (r) => (
        <span className="flex flex-wrap gap-1">
          <Badge tone={custodyTone[r.custody]}>{custodyLabel[r.custody]}</Badge>
          {(r.status === "quarantined" || r.status === "recalled") && <Badge tone={lotStatusTone[r.status]}>{humanize(r.status)}</Badge>}
        </span>
      ),
    },
    { key: "qty", header: "Length", align: "right", render: (r) => formatQty(r.qty_m, "m") },
    { key: "material", header: "Yarn", align: "right", render: (r) => formatINR(r.material) },
    { key: "machine", header: "Machine", align: "right", render: (r) => formatINR(r.machine) },
    { key: "labour", header: "Labour", align: "right", render: (r) => formatINR(r.labour) },
    { key: "chemicals", header: "Chemicals", align: "right", render: (r) => formatINR(r.chemicals) },
    { key: "total", header: "Total", align: "right", render: (r) => <span className="font-semibold">{formatINR(r.total)}</span> },
    { key: "per_m", header: "₹ / m", align: "right", render: (r) => formatINR(r.cost_per_m) },
  ];
  return (
    <Loadable state={costs}>
      {(rows) => {
        const total = rows.reduce((s, r) => s + r.total, 0);
        const metres = rows.reduce((s, r) => s + r.qty_m, 0);
        return (
          <div className="grid gap-3">
            <p className="num text-sm text-muted">
              {rows.length} rolls · {formatQty(metres, "m")} · {formatINR(total)}
              {metres > 0 && <> · {formatINR(total / metres)} per metre on average</>}
            </p>
            <DataTable columns={columns} rows={rows} rowKey={(r) => r.lot_code} emptyText="No rolls are reserved for this order yet." />
          </div>
        );
      }}
    </Loadable>
  );
}

// ---------------------------------------------------------------- profit & loss
const MONTH_TO_DATE = "";      // the API default: this month up to the last working day

/** A whole month, both ends inclusive (P&L takes mill dates, not timestamps). */
function monthDates(ym: string): { from: string; to: string } {
  const [y, m] = ym.split("-").map(Number);
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return { from: `${ym}-01`, to: `${ym}-${String(last).padStart(2, "0")}` };
}

/** One plain sentence for the owner, built only from the response. */
function pnlSentence(p: Pnl): string {
  const a = p.accrual;
  const c = p.cash;
  const result = a.profit >= 0 ? `a profit of ${formatINR(a.profit)}` : `a loss of ${formatINR(-a.profit)}`;
  const sales = a.invoices === 0 ? "Nothing was invoiced" : `${formatINR(a.revenue)} invoiced for ${a.rolls_invoiced} rolls`;
  const cash = c.net_cash >= 0 ? `cash grew by ${formatINR(c.net_cash)}` : `cash went down by ${formatINR(-c.net_cash)}`;
  let out = `${sales}: ${result} after the cost of the rolls sold and wages; ${cash}.`;
  if (p.receivables_total > 0 || p.payables_total > 0)
    out += ` Buyers owe ${formatINR(p.receivables_total)}; we owe suppliers ${formatINR(p.payables_total)}.`;
  const exposure = p.recalls.reduce((s, r) => s + r.total_exposure, 0);
  if (exposure > 0) out += ` A recall this period puts ${formatINR(exposure)} at risk, not yet in the profit.`;
  return out;
}

function ProfitAndLoss({ months }: { months: string[] }) {
  const [period, setPeriod] = useState(MONTH_TO_DATE);
  const pnl = useApi(() => {
    if (period === MONTH_TO_DATE) return api.finance.pnl();
    const w = monthDates(period);
    return api.finance.pnl(w.from, w.to);
  }, [period]);

  return (
    <section className="grid gap-6" aria-labelledby="pnl-heading">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 id="pnl-heading" className="text-xl font-semibold tracking-tight text-ink">Profit &amp; loss</h2>
          <p className="mt-1 text-sm text-muted">Did the mill make money? Two honest views: profit as booked, and cash as it moved.</p>
        </div>
        <div className="w-full max-w-xs">
          <Field label="Month">
            <Select value={period} onChange={(e) => setPeriod(e.target.value)}>
              <option value={MONTH_TO_DATE}>This month to date</option>
              {months.slice(1).map((ym) => (
                <option key={ym} value={ym}>
                  {formatMonth(ym)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </div>
      <Loadable state={pnl}>{(p) => <PnlView p={p} />}</Loadable>
    </section>
  );
}

function PnlView({ p }: { p: Pnl }) {
  const a = p.accrual;
  const c = p.cash;
  const receivableCols: Column<Pnl["receivables"][number]>[] = [
    {
      key: "buyer",
      header: "Buyer",
      render: (r) => (
        <span className="whitespace-nowrap"><span className="font-medium">{r.buyer}</span> <span className="font-mono text-muted">{r.buyer_code}</span></span>
      ),
    },
    { key: "invoices", header: "Invoices", align: "right", render: (r) => r.invoices },
    { key: "outstanding", header: "Owed to us", align: "right", render: (r) => <span className="font-semibold">{formatINR(r.outstanding)}</span> },
  ];
  const payableCols: Column<Pnl["payables"][number]>[] = [
    {
      key: "supplier",
      header: "Supplier",
      render: (r) => (
        <span className="whitespace-nowrap"><span className="font-medium">{r.supplier}</span> <span className="font-mono text-muted">{r.supplier_code}</span></span>
      ),
    },
    { key: "bills", header: "Yarn bills", align: "right", render: (r) => r.bills },
    { key: "outstanding", header: "We owe", align: "right", render: (r) => <span className="font-semibold">{formatINR(r.outstanding)}</span> },
  ];
  const basis = `${c.wages_paid_basis.charAt(0).toUpperCase()}${c.wages_paid_basis.slice(1)}`;

  return (
    <>
      <p role="status" className="rounded-lg border border-line bg-surface px-4 py-3 text-sm text-ink">
        <span className="font-medium">{formatDate(p.from)} – {formatDate(p.to)}.</span> {pnlSentence(p)}
      </p>

      <Card
        title="Profit · accrual"
        subtitle={`Revenue invoiced − cost of the rolls sold − wages. Labour is counted once: the ${formatINR(a.labour_in_lot_cost_excluded)} of operator time inside these rolls' cost is left out, because the period's wages already pay it.`}
      >
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatTile label="Revenue" value={formatINR(a.revenue)} hint={`${a.invoices} invoices · ${a.rolls_invoiced} rolls`} tone="brand" />
          <StatTile
            label="Cost of rolls sold"
            value={formatINR(a.cost_of_goods_sold)}
            hint={`Yarn ${formatINR(a.material)} · machine ${formatINR(a.machine)} · chemicals ${formatINR(a.chemicals)}`}
          />
          <StatTile label="Wages" value={formatINR(a.wages)} hint="Everyone on the register, this period" />
          <StatTile label={a.profit >= 0 ? "Profit" : "Loss"} value={formatINR(Math.abs(a.profit))} tone={a.profit >= 0 ? "ok" : "bad"} />
        </div>
      </Card>

      <Card title="Cash" subtitle="Money that actually came in and went out in the period.">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatTile label="Received from buyers" value={formatINR(c.received_from_buyers)} tone="brand" />
          <StatTile label="Yarn bills paid" value={formatINR(c.yarn_bills_paid)} />
          <StatTile label="Wages paid" value={formatINR(c.wages_paid)} hint={basis} />
          <StatTile label={c.net_cash >= 0 ? "Net cash in" : "Net cash out"} value={formatINR(Math.abs(c.net_cash))} tone={c.net_cash >= 0 ? "ok" : "bad"} />
        </div>
      </Card>

      {p.recalls.map((r) => (
        <div key={r.recall_code} className="rounded-xl border border-hold bg-hold-soft px-4 py-3 text-sm text-ink">
          <p className="font-medium">
            <Badge tone="hold">Contingent</Badge> Recall <span className="font-mono">{r.recall_code}</span> on yarn lot{" "}
            <span className="font-mono">{r.lot_code}</span>, {formatDateTime(r.applied_at)}: {formatINR(r.total_exposure)} total exposure
          </p>
          <p className="mt-1 text-muted">
            Already lost {formatINR(r.cost_already_incurred)} · newly exposed {formatINR(r.recall_exposure)} · recoverable yarn{" "}
            {formatINR(r.quarantined_material_value)}. Shown beside the profit, not subtracted: the rolls already at the buyer are
            inside the cost of rolls sold.
          </p>
        </div>
      ))}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={`Receivables · ${formatINR(p.receivables_total)}`} subtitle={`Invoiced, not yet paid, as of ${formatDate(p.to)}`} padded={false}>
          <DataTable columns={receivableCols} rows={p.receivables} rowKey={(r) => r.buyer_code} emptyText="Every invoice is paid." />
        </Card>
        <Card title={`Payables · ${formatINR(p.payables_total)}`} subtitle={`Yarn bills not yet paid, as of ${formatDate(p.to)}`} padded={false}>
          <DataTable columns={payableCols} rows={p.payables} rowKey={(r) => r.supplier_code} emptyText="Every yarn bill is paid." />
        </Card>
      </div>
    </>
  );
}
