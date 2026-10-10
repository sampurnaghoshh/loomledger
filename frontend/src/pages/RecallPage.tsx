// Recall: everything a root lot touched, what it costs, which buyers wait longer, and one button to quarantine it all.
import { useState } from "react";
import { useParams } from "react-router-dom";
import { Ban, Factory, ShieldAlert, ShieldCheck } from "lucide-react";
import { api } from "@/api/client";
import type { ApiError } from "@/api/errors";
import type { Custody, RecallOrderImpact, RecallResponse, RecallRoll } from "@/api/types";
import { LotGraph } from "@/components/LotGraph";
import { Badge, Button, Card, DataTable, EmptyState, ErrorBanner, Field, Loadable, Modal, PageHeader, StatTile, Textarea, type Column } from "@/components/ui";
import { useAction, useApi } from "@/hooks/useApi";
import { formatDate, formatDateTime, formatINR, formatQty, humanize, newIdempotencyKey } from "@/lib/format";
import { custodyLabel, custodyTone } from "@/lib/tones";

// Greige product woven from yarn. No endpoint exposes product codes yet; this is the contract's example
// for POST /api/production/weaving-runs (docs/API_CONTRACT.md). Only valid for twill lots (poplin yarn weaves
// GRG-POP). Replace once a products endpoint exists.
const GREIGE_PRODUCT_CODE = "GRG-TWL";

// Most urgent first: what's already bad, what's already left the building, then what we can still stop.
const CUSTODY_ORDER: Custody[] = ["rejected", "at_customer", "passed_in_store", "awaiting_qc", "rework", "wip", "consumed"];

/** "1 roll" / "3 rolls" */
const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export default function RecallPage() {
  const { lotCode = "" } = useParams<{ lotCode: string }>();
  // No lot in the URL: skip the request entirely.
  const recall = useApi(() => (lotCode ? api.recalls.preview(lotCode) : Promise.resolve(null)), [lotCode]);

  if (!lotCode) {
    return (
      <Card>
        <EmptyState title="No lot selected" body="Open a recall from Find Cause, or go to /recall/<lot code>." />
      </Card>
    );
  }

  return (
    <Loadable state={recall}>
      {(data) => data && <RecallView data={data} onApplied={(next) => recall.setData(next)} />}
    </Loadable>
  );
}

function RecallView({ data, onApplied }: { data: RecallResponse; onApplied: (next: RecallResponse) => void }) {
  const { impact, calculation } = data;
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [staleNotice, setStaleNotice] = useState(false);

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <PageHeader
        title={`Recall ${data.lot_code}`}
        subtitle={
          data.applied ? (
            <span className="flex flex-wrap items-center gap-2">
              <Badge tone="hold">
                <ShieldCheck className="size-3.5" aria-hidden /> Quarantined · <span className="whitespace-nowrap font-mono">{data.recall_code}</span>
              </Badge>
              {data.applied_at && <span>applied {formatDateTime(data.applied_at)}</span>}
            </span>
          ) : (
            <span className="flex flex-wrap items-center gap-2">
              <Badge tone="warn">Preview</Badge>
              <span>Nothing has been quarantined yet.</span>
            </span>
          )
        }
        actions={
          !data.applied && (
            <Button variant="danger" icon={<ShieldAlert className="size-4" />} onClick={() => setConfirmOpen(true)}>
              Apply recall
            </Button>
          )
        }
      />

      {staleNotice && !data.applied && (
        <div role="alert" className="rounded-lg border border-warn bg-warn-soft px-4 py-3 text-sm font-medium text-warn">
          This recall is no longer applied on the database (it may have been reset). Apply it again first.
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile
          label="Rolls affected"
          value={impact.rolls_total}
          tone="bad"
          hint={`${impact.rolls_rejected} rejected + ${impact.rolls_at_risk} at risk`}
        />
        <StatTile
          label="Orders affected"
          value={impact.orders_affected}
          tone="warn"
          hint={`${count(impact.buyers_affected, "buyer")} · ${impact.buyers_holding_goods} already holding goods`}
        />
        <StatTile
          label="Remake"
          value={formatQty(impact.remake_m, "m")}
          hint={
            impact.bottleneck_stage && impact.throughput_m_per_day != null
              ? `${humanize(impact.bottleneck_stage)} bottleneck · ${formatQty(impact.throughput_m_per_day, "m")}/day`
              : undefined
          }
        />
        <StatTile
          label="Delay"
          value={`+${count(impact.additional_delay_days, "working day")}`}
          tone="warn"
          hint={<span className="num">{calculation.display}</span>}
        />
      </div>

      <MoneyRow data={data} />

      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-2">
        <RollsByCustody rolls={data.rolls} />
        <OrdersTable orders={data.orders} />
      </div>

      {data.applied && (
        <TryIssuePanel
          lotCode={data.lot_code}
          rolls={data.rolls}
          onNotApplied={(fresh) => {
            setStaleNotice(true);
            onApplied(fresh);
          }}
        />
      )}

      <RecallGenealogy lotCode={data.lot_code} applied={data.applied} />

      <ApplyModal
        open={confirmOpen}
        lotCode={data.lot_code}
        onClose={() => setConfirmOpen(false)}
        onApplied={(next) => {
          setConfirmOpen(false);
          setStaleNotice(false);
          onApplied(next);
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------- genealogy
function RecallGenealogy({ lotCode, applied }: { lotCode: string; applied: boolean }) {
  // Re-fetch when the recall is applied so quarantine shows on every node.
  const graph = useApi(() => api.trace.descendants(lotCode), [lotCode, applied]);
  return (
    <Card
      title="Everything this lot touched"
      subtitle={<>Every lot made from <span className="whitespace-nowrap font-mono">{lotCode}</span>, coloured by where it is now</>}
    >
      <Loadable state={graph}>
        {(g) =>
          g.nodes.length <= 1 ? (
            <EmptyState title="Nothing has been made from this lot yet" />
          ) : (
            <LotGraph graph={g} colorBy="custody" rootCause={lotCode} rootLabel="Recall source" />
          )
        }
      </Loadable>
    </Card>
  );
}

// ---------------------------------------------------------------- money
function MoneyRow({ data }: { data: RecallResponse }) {
  const { impact } = data;
  const parts = [
    { label: "Already lost", value: impact.cost_already_incurred, hint: count(impact.rolls_rejected, "rejected roll") },
    { label: "Newly exposed", value: impact.recall_exposure, hint: `${count(impact.rolls_at_risk, "roll")} at risk` },
    {
      label: "Recoverable yarn",
      value: impact.quarantined_material_value,
      hint: `${formatQty(impact.quarantined_material_qty, "kg")} quarantined`,
    },
  ];
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1fr_1fr_1.4fr]">
      {parts.map((p) => (
        <div key={p.label} className="rounded-xl border border-line bg-surface p-5 shadow-sm">
          <p className="text-sm font-medium uppercase tracking-wide text-muted">{p.label}</p>
          <p className="num mt-1 text-3xl font-semibold text-ink">{formatINR(p.value)}</p>
          <p className="num mt-1 text-sm text-muted">{p.hint}</p>
        </div>
      ))}
      <div className="rounded-xl border-2 border-bad bg-bad-soft p-5 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-wide text-bad">Total exposure</p>
        <p className="num mt-1 text-4xl font-bold text-bad lg:text-5xl">{formatINR(impact.total_exposure)}</p>
        <p className="mt-1 text-sm text-bad">lost + exposed + recoverable yarn</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- rolls
function RollsByCustody({ rolls }: { rolls: RecallRoll[] }) {
  const groups = CUSTODY_ORDER.map((custody) => {
    const items = rolls.filter((r) => r.custody === custody);
    return { custody, items, subtotal: items.reduce((s, r) => s + r.cost, 0) };
  }).filter((g) => g.items.length > 0);

  return (
    <Card title="Affected rolls" subtitle="Where each roll is right now">
      {groups.length === 0 ? (
        <EmptyState title="No rolls descend from this lot" />
      ) : (
        <ul className="grid gap-3">
          {groups.map((g) => {
            const atCustomer = g.custody === "at_customer";
            return (
              <li
                key={g.custody}
                className={`rounded-lg border p-3 ${atCustomer ? "border-2 border-accent bg-accent-soft" : "border-line"}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex items-center gap-2">
                    <Badge tone={custodyTone[g.custody]}>{custodyLabel[g.custody]}</Badge>
                    <span className="num text-sm font-medium text-ink">{count(g.items.length, "roll")}</span>
                  </span>
                  <span className="num text-sm font-semibold text-ink">{formatINR(g.subtotal)}</span>
                </div>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {g.items.map((r) => (
                    <li
                      key={r.lot_code}
                      className="rounded-md border border-line bg-surface px-2 py-1 text-sm"
                      title={`${formatQty(r.qty_m, "m")} · ${formatINR(r.cost)}`}
                    >
                      <span className="whitespace-nowrap font-mono text-ink">{r.lot_code}</span>
                      {atCustomer && r.buyer_name && <span className="ml-2 font-medium text-accent">{r.buyer_name}</span>}
                    </li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- orders
function OrdersTable({ orders }: { orders: RecallOrderImpact[] }) {
  const columns: Column<RecallOrderImpact>[] = [
    { key: "order", header: "Order", render: (o) => <span className="whitespace-nowrap font-mono font-medium">{o.order_code}</span> },
    { key: "buyer", header: "Buyer", render: (o) => o.buyer_name },
    { key: "affected", header: "Rolls", align: "right", render: (o) => o.affected_rolls },
    {
      key: "at_customer",
      header: "At buyer",
      align: "right",
      render: (o) => (o.rolls_at_customer > 0 ? <Badge tone="accent">{o.rolls_at_customer}</Badge> : <span className="text-muted">0</span>),
    },
    {
      key: "dates",
      header: "Promised → revised",
      render: (o) => (
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1 whitespace-nowrap">
          <span className="text-muted line-through">{formatDate(o.promised_date)}</span>
          <span>→</span>
          <span className="font-semibold">{formatDate(o.revised_promise_date)}</span>
          <Badge tone="warn">+{count(o.delay_days, "day")}</Badge>
        </span>
      ),
    },
  ];
  return (
    <Card title="Orders delayed" subtitle="New promise dates the buyers will see" padded={false}>
      <DataTable columns={columns} rows={orders} rowKey={(o) => o.order_code} emptyText="No open orders are affected." />
    </Card>
  );
}

// ---------------------------------------------------------------- apply
function ApplyModal({
  open,
  lotCode,
  onClose,
  onApplied,
}: {
  open: boolean;
  lotCode: string;
  onClose: () => void;
  onApplied: (next: RecallResponse) => void;
}) {
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string>();
  const apply = useAction(api.recalls.apply);

  async function submit() {
    const trimmed = reason.trim();
    if (trimmed.length < 3) {
      setReasonError("Give a reason (at least 3 characters) — it goes on the recall record.");
      return;
    }
    setReasonError(undefined);
    const res = await apply.run(lotCode, trimmed);
    if (res) onApplied(res);
  }

  return (
    <Modal
      open={open}
      onClose={apply.running ? () => undefined : onClose}
      title={<>Apply recall on <span className="whitespace-nowrap font-mono">{lotCode}</span>?</>}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={apply.running}>
            Cancel
          </Button>
          <Button variant="danger" loading={apply.running} onClick={submit}>
            Quarantine everything
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <p className="text-sm text-ink">
          Every lot descending from <span className="whitespace-nowrap font-mono">{lotCode}</span> will be quarantined and the affected buyers' dates
          revised. The database will refuse any further movement of this stock.
        </p>
        <ErrorBanner error={apply.error} />
        <Field label="Reason" error={reasonError}>
          <Textarea
            value={reason}
            aria-invalid={!!reasonError}
            placeholder="e.g. colour mismatch traced to this yarn lot"
            onChange={(e) => setReason(e.target.value)}
            disabled={apply.running}
          />
        </Field>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- the database says no
function TryIssuePanel({
  lotCode,
  rolls,
  onNotApplied,
}: {
  lotCode: string;
  rolls: RecallRoll[];
  onNotApplied: (fresh: RecallResponse) => void;
}) {
  const machines = useApi(() => api.floor.machines(), []);
  const [idempotencyKey] = useState(newIdempotencyKey);
  const recheck = useAction(api.recalls.preview);
  const attempt = useAction(api.production.startWeaving);
  const [started, setStarted] = useState<string | null>(null);

  // A roll-sized run: the length of the greige roll this lot was feeding (falls back to any affected roll).
  const meters = (rolls.find((r) => r.kind === "greige") ?? rolls[0])?.qty_m;
  const loom = machines.data?.find((m) => m.stage === "weaving" && m.state === "idle");

  async function tryIssue() {
    if (!loom || !meters) return;
    setStarted(null);
    attempt.clearError();
    // Never act on stale page state: on the real backend this call would start a run if the lot is not quarantined.
    const fresh = await recheck.run(lotCode);
    if (!fresh) return;
    if (!fresh.applied) {
      onNotApplied(fresh);
      return;
    }
    const res = await attempt.run({
      machine_code: loom.code,
      yarn_lot_code: lotCode,
      product_code: GREIGE_PRODUCT_CODE,
      meters_planned: meters,
      idempotency_key: idempotencyKey,
    });
    if (res) setStarted(res.run_code);
  }

  const refused = attempt.error?.code === "LOT_QUARANTINED" ? attempt.error : null;
  const forbidden = attempt.error?.code === "FORBIDDEN";
  const sqlstate = refused ? (refused as ApiError & { sqlstate?: string }).sqlstate : undefined;

  return (
    <Card
      title={<>Try issuing <span className="whitespace-nowrap font-mono">{lotCode}</span> to a loom</>}
      subtitle="Start a weaving run with the quarantined yarn. PostgreSQL itself should refuse."
    >
      <Loadable state={machines}>
        {() => (
          <div className="grid gap-4">
            {!loom ? (
              <p className="text-sm text-muted">No idle loom right now — free a loom on the floor board to run this check.</p>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="secondary" icon={<Factory className="size-4" />} loading={recheck.running || attempt.running} onClick={tryIssue} disabled={!meters}>
                  Issue <span className="whitespace-nowrap font-mono">{lotCode}</span> to {loom.name}
                </Button>
                <span className="num text-sm text-muted">
                  {formatQty(meters, "m")} of <span className="whitespace-nowrap font-mono">{GREIGE_PRODUCT_CODE}</span>
                </span>
              </div>
            )}

            {refused && (
              <div role="alert" className="flex items-start gap-4 rounded-xl border-2 border-bad bg-bad-soft p-5 text-bad">
                <Ban className="mt-1 size-8 shrink-0" aria-hidden />
                <div className="grid gap-1">
                  <p className="text-2xl font-bold">The database refused</p>
                  <p className="font-mono text-lg">{refused.message}</p>
                  {refused.hint && <p className="text-base">{refused.hint}</p>}
                  <p className="font-mono text-sm">
                    {refused.code} · HTTP {refused.status}
                    {sqlstate && <> · SQLSTATE {sqlstate}</>}
                  </p>
                </div>
              </div>
            )}

            {recheck.error && <ErrorBanner error={recheck.error} onRetry={tryIssue} />}
            {forbidden && (
              <div role="status" className="rounded-lg border border-line bg-idle-soft px-4 py-3 text-sm text-ink">
                Your role can't start weaving runs. Sign in as owner or floor supervisor to run this check.
              </div>
            )}
            {attempt.error && !refused && !forbidden && <ErrorBanner error={attempt.error} onRetry={tryIssue} />}

            {started && (
              <div role="alert" className="rounded-lg border border-warn bg-warn-soft px-4 py-3 text-sm text-warn">
                <p className="font-medium">
                  Run <span className="whitespace-nowrap font-mono">{started}</span> was started — the quarantine guard did not fire.
                </p>
                <p className="mt-0.5">Check that the recall was applied on this database.</p>
              </div>
            )}
          </div>
        )}
      </Loadable>
    </Card>
  );
}
