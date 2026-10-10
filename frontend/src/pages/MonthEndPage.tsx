// Close of the demo: the yarn mass balance to date (where every issued kilo went, and which loom loses it)
// and the true cost of every roll on an order. Accounts and the owner only.
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Lock } from "lucide-react";
import { api } from "@/api/client";
import type { MassBalance, OrderSummary, RollCost } from "@/api/types";
import { Badge, Card, DataTable, EmptyState, Field, Loadable, PageHeader, Select, StatTile, type Column } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { getSession } from "@/lib/auth";
import { formatDate, formatINR, formatMonth, formatPct, formatQty, humanize } from "@/lib/format";
import { custodyLabel, custodyTone, lotStatusTone } from "@/lib/tones";

const ALLOWED_ROLES = ["owner", "accounts"];
const TO_DATE = "";            // period value for "everything so far" (the locked Close figure)
const MONTHS_BACK = 3;         // the current month and the two before it

export default function MonthEndPage() {
  const role = getSession()?.user.role;
  return (
    <div className="grid gap-6">
      <PageHeader title="Month-end" subtitle="Yarn mass balance and the true cost of every roll" />
      {role && ALLOWED_ROLES.includes(role) ? <MonthEnd /> : <NotAllowed />}
    </div>
  );
}

function NotAllowed() {
  return (
    <Card>
      <EmptyState
        title="Month-end figures are for Accounts"
        body="Sign in as accounts@ or owner@ to see the mass balance and roll costs."
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
