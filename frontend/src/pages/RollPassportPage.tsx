// Roll passport: what a phone sees after scanning a roll's QR label. 375 px first; everything comes from
// GET /api/rolls/{code}/passport (the family tree, QC, true cost, order, dispatch and recall, all derived in the DB).
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { ClipboardCheck, Factory, GitBranch, Package, ShieldAlert, Truck, Wheat } from "lucide-react";
import { api } from "@/api/client";
import type { RollPassport, RollPassportStep } from "@/api/types";
import { Badge, Card, Loadable } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { formatDate, formatDateTime, formatINR, formatQty, humanize } from "@/lib/format";
import { passportBanner, type Tone } from "@/lib/tones";

const bannerClasses: Record<Tone, string> = {
  ok: "bg-ok text-surface",
  warn: "bg-warn text-surface",
  bad: "bg-bad text-surface",
  hold: "bg-hold text-surface",
  brand: "bg-brand text-surface",
  accent: "bg-accent text-surface",
  idle: "bg-idle text-surface",
};
const dotClasses: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  hold: "bg-hold",
  brand: "bg-brand",
  accent: "bg-accent",
  idle: "bg-idle",
};

export default function RollPassportPage() {
  const { code = "" } = useParams<{ code: string }>();
  const passport = useApi(() => api.rolls.passport(code), [code]);

  return (
    <div className="min-h-screen bg-canvas">
      <header className="flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3">
        <p className="text-sm font-semibold text-ink">
          LoomLedger <span className="font-normal text-muted">· Roll passport</span>
        </p>
        <Link to="/floor" className="text-sm font-medium text-brand underline">
          Open app
        </Link>
      </header>
      <main className="mx-auto grid max-w-xl gap-4 px-4 py-4 md:py-8">
        <Loadable state={passport}>{(p) => <Passport p={p} />}</Loadable>
      </main>
    </div>
  );
}

function Passport({ p }: { p: RollPassport }) {
  const banner = passportBanner(p);
  const yarn = p.lineage.find((s) => s.kind === "yarn");
  return (
    <>
      <section className={`rounded-2xl p-5 shadow-sm ${bannerClasses[banner.tone]}`} aria-label="Roll status">
        <p className="text-2xl font-extrabold leading-tight tracking-wide break-words sm:text-3xl">{banner.label}</p>
        <p className="mt-3 font-mono text-3xl font-bold">{p.code}</p>
        <p className="num mt-1 text-sm opacity-90">
          {p.product} · {formatQty(p.qty_m, "m")}
        </p>
      </section>

      {p.recall && (
        <div role="status" className="flex items-start gap-3 rounded-xl border-2 border-hold bg-hold-soft p-4 text-hold">
          <ShieldAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
          <div className="min-w-0 text-sm">
            <p className="font-semibold">
              Under recall <span className="whitespace-nowrap font-mono">{p.recall.code}</span>
            </p>
            <p className="text-ink">{p.recall.reason}</p>
            <p className="mt-1 text-muted">Since {formatDateTime(p.recall.initiated_at)}</p>
          </div>
        </div>
      )}

      <Card title="Where it came from" subtitle="Its family tree, oldest first" padded={false}>
        <ol className="px-5 py-4">
          {p.lineage.map((step) => (
            <TimelineItem key={step.lot_code} tone={step.kind === "yarn" ? "accent" : "brand"} icon={step.kind === "yarn" ? <Wheat className="size-4" /> : <Factory className="size-4" />}>
              <StepBody step={step} isRoll={step.depth === 0} />
            </TimelineItem>
          ))}
          <TimelineItem
            tone={p.qc ? (p.qc.result === "pass" ? "ok" : p.qc.result === "reject" ? "bad" : "warn") : "idle"}
            icon={<ClipboardCheck className="size-4" />}
          >
            {p.qc ? (
              <>
                <p className="font-medium text-ink">
                  QC {p.qc.result === "pass" ? "passed" : p.qc.result === "reject" ? "rejected" : "sent to rework"}
                  {p.qc.defect_type && <> · {humanize(p.qc.defect_type)}</>}
                </p>
                <p className="text-sm text-muted">
                  {p.qc.inspector} · {formatDateTime(p.qc.inspected_at)}
                  {p.qc.defect_m != null && <> · {formatQty(p.qc.defect_m, "m")} defective</>}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted">Not inspected yet</p>
            )}
          </TimelineItem>
          <TimelineItem tone={p.order ? "brand" : "idle"} icon={<Package className="size-4" />}>
            {p.order ? (
              <>
                <p className="font-medium text-ink">
                  For <span className="whitespace-nowrap font-mono">{p.order.code}</span> · {p.order.buyer}
                </p>
                <p className="text-sm">
                  {p.order.revised_promise_date ? (
                    <>
                      <span className="text-muted line-through">{formatDate(p.order.promised_date)}</span>{" "}
                      <span className="font-semibold text-bad">→ {formatDate(p.order.revised_promise_date)}</span>
                    </>
                  ) : (
                    <span className="text-muted">Promised {formatDate(p.order.promised_date)}</span>
                  )}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted">Not reserved for an order</p>
            )}
          </TimelineItem>
          {p.dispatch && (
            <TimelineItem tone="accent" icon={<Truck className="size-4" />}>
              <p className="font-medium text-ink">
                Shipped · <span className="whitespace-nowrap font-mono">{p.dispatch.code}</span>
              </p>
              <p className="text-sm text-muted">
                {formatDateTime(p.dispatch.dispatched_at)}
                {p.dispatch.vehicle_no && <> · <span className="whitespace-nowrap font-mono">{p.dispatch.vehicle_no}</span></>}
                {p.dispatch.invoice_code && <> · invoice <span className="whitespace-nowrap font-mono">{p.dispatch.invoice_code}</span></>}
              </p>
            </TimelineItem>
          )}
        </ol>
      </Card>

      <Card title="True cost" subtitle={p.kind === "greige" && !p.lineage[p.lineage.length - 1]?.run?.ended_at ? "On the loom: material only so far" : "Material + machine + labour + chemicals"}>
        <p className="num text-3xl font-semibold text-ink">{formatINR(p.cost.total)}</p>
        <p className="num text-sm text-muted">{formatINR(p.cost.cost_per_m)} per metre</p>
        <dl className="num mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          {(["material", "machine", "labour", "chemicals"] as const).map((k) => (
            <div key={k} className="flex justify-between gap-2">
              <dt className="text-muted">{humanize(k)}</dt>
              <dd className="text-ink">{formatINR(p.cost[k])}</dd>
            </div>
          ))}
        </dl>
      </Card>

      {yarn && (
        <Link
          to={`/recall/${encodeURIComponent(yarn.lot_code)}`}
          className="hidden items-center justify-center gap-2 rounded-lg border border-line bg-surface px-4 py-3 text-sm font-medium text-brand hover:bg-brand-soft md:flex"
        >
          <GitBranch className="size-4" aria-hidden />
          Open the genealogy graph of <span className="font-mono">{yarn.lot_code}</span>
        </Link>
      )}
    </>
  );
}

function StepBody({ step, isRoll }: { step: RollPassportStep; isRoll: boolean }) {
  const qty = formatQty(step.qty, step.uom);
  if (step.receipt)
    return (
      <>
        <p className="font-medium text-ink">
          Yarn lot <span className="whitespace-nowrap font-mono">{step.lot_code}</span>
        </p>
        <p className="text-sm text-muted">
          {step.product} · {qty}
        </p>
        <p className="text-sm text-muted">
          Received from {step.receipt.supplier} · {formatDate(step.receipt.received_at)}
        </p>
      </>
    );
  const run = step.run;
  return (
    <>
      <p className="flex flex-wrap items-center gap-x-2 font-medium text-ink">
        {run ? humanize(run.stage) : humanize(step.kind)} · <span className="whitespace-nowrap font-mono">{step.lot_code}</span>
        {isRoll && <Badge tone="brand">This roll</Badge>}
      </p>
      <p className="text-sm text-muted">
        {step.product} · {qty}
      </p>
      {run && (
        <p className="text-sm text-muted">
          {run.machine} · {run.shift} · {run.operator}
          <br />
          {formatDateTime(run.started_at)} → {run.ended_at ? formatDateTime(run.ended_at) : "still on the machine"}
        </p>
      )}
    </>
  );
}

function TimelineItem({ tone, icon, children }: { tone: Tone; icon: ReactNode; children: ReactNode }) {
  return (
    <li className="group relative flex gap-3 pb-5 last:pb-0">
      <span className="absolute left-[13px] top-7 bottom-0 w-px bg-line group-last:hidden" aria-hidden />
      <span className={`relative flex size-7 shrink-0 items-center justify-center rounded-full text-surface ${dotClasses[tone]}`} aria-hidden>
        {icon}
      </span>
      <div className="min-w-0 pt-0.5">{children}</div>
    </li>
  );
}
