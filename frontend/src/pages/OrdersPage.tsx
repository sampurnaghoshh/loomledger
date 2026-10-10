// Orders: where every order stands, the buyer's tracking link (Act 4 jumps from here to the buyer's phone), and dispatch.
import { useState } from "react";
import { Ban, Check, Copy, ExternalLink, Truck } from "lucide-react";
import { api } from "@/api/client";
import type { ApiError, ApiErrorCode } from "@/api/errors";
import type { DispatchRequest, DispatchResponse, OrderProgress, OrderSummary, RollCost } from "@/api/types";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Input, Loadable, Modal, PageHeader, Textarea } from "@/components/ui";
import { useAction, useApi } from "@/hooks/useApi";
import { formatDate, formatINR, formatQty, humanize, newIdempotencyKey } from "@/lib/format";
import { custodyLabel, custodyTone, lotStatusTone, type Tone } from "@/lib/tones";

/** "1 roll" / "3 rolls" */
const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

const statusTone: Record<OrderSummary["status"], Tone> = {
  confirmed: "idle",
  in_production: "brand",
  partially_dispatched: "accent",
  dispatched: "ok",
  cancelled: "idle",
};

// Progress segments: five clearly different tones (done = navy, in process = grey).
const SEGMENTS: { key: keyof OrderProgress; label: string; tone: Tone }[] = [
  { key: "dispatched_m", label: "Dispatched", tone: "brand" },
  { key: "ready_m", label: "Ready", tone: custodyTone.passed_in_store },
  { key: "quality_check_m", label: "Quality check", tone: custodyTone.awaiting_qc },
  { key: "weaving_m", label: "Weaving", tone: "idle" },
  { key: "on_hold_m", label: "On hold", tone: lotStatusTone.quarantined },
];
const segmentFill: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  hold: "bg-hold",
  brand: "bg-brand",
  accent: "bg-accent",
  idle: "bg-idle",
};

// The database refused the dispatch: show it as proof, not as a crash.
const REFUSED: ApiErrorCode[] = ["NOT_QC_PASSED", "LOT_QUARANTINED", "NOT_IN_ORDER", "ALREADY_DISPATCHED", "INSUFFICIENT_STOCK"];
// Fixed actions column so every row lines up whether or not it has a Dispatch button.
const COLUMNS = "xl:grid-cols-[minmax(0,1.2fr)_9.5rem_minmax(0,1.1fr)_minmax(0,1.4fr)_15rem]";

/** Working days (Mon–Sat, as add_working_days() in the DB) from one ISO date to a later one. */
function workingDaysBetween(from: string, to: string): number {
  const day = 86_400_000;
  const start = Date.UTC(+from.slice(0, 4), +from.slice(5, 7) - 1, +from.slice(8, 10));
  const end = Date.UTC(+to.slice(0, 4), +to.slice(5, 7) - 1, +to.slice(8, 10));
  let n = 0;
  for (let t = start + day; t <= end; t += day) if (new Date(t).getUTCDay() !== 0) n++;
  return n;
}

export default function OrdersPage() {
  const orders = useApi(() => api.orders.list(), []);
  const [dispatchFor, setDispatchFor] = useState<OrderSummary | null>(null);

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <PageHeader title="Orders" subtitle="Where every order stands, and the live link each buyer sees on their phone." />

      <Card padded={false}>
        <Loadable state={orders}>
          {(rows) =>
            rows.length === 0 ? (
              <EmptyState title="No orders yet" />
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-5 py-3 text-xs text-muted">
                  {SEGMENTS.map((s) => (
                    <span key={s.key} className="flex items-center gap-1.5">
                      <span className={`size-2.5 rounded-sm ${segmentFill[s.tone]}`} aria-hidden />
                      {s.label}
                    </span>
                  ))}
                </div>
                <div className={`hidden gap-4 border-b border-line px-5 py-2 text-xs font-medium uppercase tracking-wide text-muted xl:grid ${COLUMNS}`}>
                  <span>Order</span>
                  <span>Status</span>
                  <span>Promised → revised</span>
                  <span>Progress</span>
                  <span className="sr-only">Actions</span>
                </div>
                <ul>
                  {rows.map((o) => (
                    <OrderRow key={o.code} order={o} onDispatch={() => setDispatchFor(o)} />
                  ))}
                </ul>
              </>
            )
          }
        </Loadable>
      </Card>

      {dispatchFor && (
        <DispatchModal order={dispatchFor} onClose={() => setDispatchFor(null)} onDispatched={() => void orders.reload()} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------- one order
function OrderRow({ order: o, onDispatch }: { order: OrderSummary; onDispatch: () => void }) {
  const [copied, setCopied] = useState<"ok" | "failed" | null>(null);
  const path = `/track/${encodeURIComponent(o.tracking_token)}`;
  const late = o.revised_promise_date != null && o.revised_promise_date > o.promised_date;
  const canDispatch = o.status !== "dispatched" && o.status !== "cancelled";

  async function copy() {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}${path}`);
      setCopied("ok");
    } catch {
      setCopied("failed");
    }
    setTimeout(() => setCopied(null), 2000);
  }

  return (
    <li className={`grid gap-3 border-b border-line px-5 py-4 last:border-0 xl:items-center xl:gap-4 ${COLUMNS}`}>
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-x-2">
          <span className="whitespace-nowrap font-mono font-semibold text-ink">{o.code}</span>
          <span className="font-medium text-ink">{o.buyer}</span>
        </p>
        <p className="num text-sm text-muted">
          {o.product} · <span className="whitespace-nowrap text-ink">{formatQty(o.ordered_m, "m")}</span> ordered
        </p>
      </div>

      <div>
        <Badge tone={statusTone[o.status]}>{humanize(o.status)}</Badge>
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        {late ? (
          <>
            <span className="whitespace-nowrap text-muted line-through">{formatDate(o.promised_date)}</span>
            <span aria-hidden>→</span>
            <span className="whitespace-nowrap font-semibold text-bad">{formatDate(o.revised_promise_date)}</span>
            <Badge tone="bad">+{count(workingDaysBetween(o.promised_date, o.revised_promise_date!), "working day")}</Badge>
          </>
        ) : (
          <span className="whitespace-nowrap text-ink">{formatDate(o.promised_date)}</span>
        )}
      </div>

      <ProgressBar order={o} />

      <div className="flex flex-wrap items-center gap-2 xl:justify-end">
        <Button variant="secondary" size="sm" icon={<ExternalLink className="size-4" />} onClick={() => window.open(path, "_blank", "noopener")}>
          Buyer link
        </Button>
        <Button
          variant="ghost"
          size="sm"
          icon={copied === "ok" ? <Check className="size-4 text-ok" /> : <Copy className="size-4" />}
          onClick={copy}
          aria-label={`Copy buyer link for ${o.code}`}
        >
          {copied === "ok" ? "Copied" : copied === "failed" ? "Copy failed" : "Copy link"}
        </Button>
        {canDispatch && (
          <Button size="sm" icon={<Truck className="size-4" />} onClick={onDispatch}>
            Dispatch rolls
          </Button>
        )}
      </div>
    </li>
  );
}

function ProgressBar({ order }: { order: OrderSummary }) {
  const parts = SEGMENTS.map((s) => ({ ...s, m: order.progress[s.key] })).filter((s) => s.m > 0);
  const total = Math.max(order.ordered_m, 1);
  return (
    <div className="grid gap-1.5">
      <div
        className="flex h-2.5 overflow-hidden rounded-full bg-idle-soft"
        role="img"
        aria-label={parts.map((p) => `${p.label} ${formatQty(p.m, "m")}`).join(", ") || "Not started"}
      >
        {parts.map((p) => (
          <div key={p.key} className={segmentFill[p.tone]} style={{ width: `${Math.min(100, (p.m / total) * 100)}%` }} />
        ))}
      </div>
      <p className="num flex flex-wrap gap-x-3 text-xs text-muted">
        {parts.length === 0
          ? "Not started"
          : parts.map((p) => (
              <span key={p.key} className="whitespace-nowrap">
                {p.label} {formatQty(p.m, "m")}
              </span>
            ))}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------- dispatch
type FieldErrors = { vehicle_no?: string; lot_codes?: string; shade_override_reason?: string };

function DispatchModal({ order, onClose, onDispatched }: { order: OrderSummary; onClose: () => void; onDispatched: () => void }) {
  const rolls = useApi(() => api.finance.rollCosts(order.code), [order.code]);
  const [idempotencyKey] = useState(newIdempotencyKey); // one per modal: every resend reuses it
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showAll, setShowAll] = useState(false);
  const [vehicle, setVehicle] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [local, setLocal] = useState<FieldErrors>({});
  const [result, setResult] = useState<DispatchResponse | null>(null);
  const dispatch = useAction(api.orders.dispatch);

  const err = dispatch.error;
  const shade = err?.code === "SHADE_MISMATCH" ? err : null;
  const refused = err && REFUSED.includes(err.code) ? err : null;
  const forbidden = err?.code === "FORBIDDEN";
  const serverFields: FieldErrors = err?.code === "VALIDATION_FAILED" ? (err.fields ?? {}) : {};
  const fieldError = (k: keyof FieldErrors) => local[k] ?? serverFields[k];

  function toggle(code: string) {
    // A new selection is a new question: drop the last refusal (incl. the shade override prompt).
    if (dispatch.error) dispatch.clearError();
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  async function submit() {
    const withOverride = !!shade;
    const errs: FieldErrors = {};
    if (!vehicle.trim()) errs.vehicle_no = "Enter the vehicle number.";
    if (selected.size === 0) errs.lot_codes = "Pick at least one roll.";
    const reason = overrideReason.trim();
    if (withOverride && (reason.length < 3 || reason.length > 500)) errs.shade_override_reason = "Give a reason of 3–500 characters.";
    setLocal(errs);
    if (Object.keys(errs).length) return;

    const req: DispatchRequest = {
      order_code: order.code,
      lot_codes: [...selected],
      vehicle_no: vehicle.trim(),
      idempotency_key: idempotencyKey,
      ...(withOverride ? { shade_override_reason: reason } : {}),
    };
    const res = await dispatch.run(req);
    if (res) {
      setResult(res);
      onDispatched();
    }
  }

  const busy = dispatch.running;
  return (
    <Modal
      open
      onClose={busy ? () => undefined : onClose}
      title={<>Dispatch rolls · <span className="whitespace-nowrap font-mono">{order.code}</span></>}
      footer={
        result ? (
          <Button onClick={onClose}>Done</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button variant={shade ? "danger" : "primary"} loading={busy} onClick={submit} icon={<Truck className="size-4" />}>
              {shade ? "Dispatch anyway" : selected.size ? `Dispatch ${count(selected.size, "roll")}` : "Dispatch"}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <div className="grid gap-3">
          <p className="flex items-center gap-2 font-medium text-ok">
            <Check className="size-5" aria-hidden /> Dispatched to {order.buyer}
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted">Dispatch</dt>
            <dd className="whitespace-nowrap font-mono">{result.dispatch_code}</dd>
            <dt className="text-muted">Invoice</dt>
            <dd className="whitespace-nowrap font-mono">{result.invoice_code}</dd>
            <dt className="text-muted">Amount</dt>
            <dd className="num font-semibold">{formatINR(result.amount)}</dd>
          </dl>
        </div>
      ) : (
        // The shared Modal has no max height: scroll the body so the footer buttons stay on screen on phones.
        <div className="-mx-1 grid max-h-[65dvh] gap-4 overflow-y-auto px-1">
          <Loadable state={rolls}>
            {(list) => (
              <RollPicker
                rolls={list}
                selected={selected}
                onToggle={toggle}
                showAll={showAll}
                onShowAll={setShowAll}
                disabled={busy}
                error={fieldError("lot_codes")}
              />
            )}
          </Loadable>

          <Field label="Vehicle number" error={fieldError("vehicle_no")}>
            <Input
              value={vehicle}
              onChange={(e) => setVehicle(e.target.value)}
              aria-invalid={!!fieldError("vehicle_no")}
              autoComplete="off"
              disabled={busy}
            />
          </Field>

          {shade && (
            <div className="grid gap-3 rounded-lg border border-warn bg-warn-soft p-4 text-sm text-warn">
              <div>
                <p className="font-semibold">These rolls come from different dye batches</p>
                {shade.fields?.batches && (
                  <p className="mt-0.5">
                    Batches: <span className="whitespace-nowrap font-mono">{shade.fields.batches}</span>
                  </p>
                )}
                <p className="mt-1 text-ink">
                  One dispatch must be a single dye batch so the buyer gets one shade. Pick rolls from one batch, or record why this
                  mix is acceptable and dispatch anyway.
                </p>
              </div>
              <Field label="Override reason" error={fieldError("shade_override_reason")}>
                <Textarea
                  value={overrideReason}
                  onChange={(e) => setOverrideReason(e.target.value)}
                  aria-invalid={!!fieldError("shade_override_reason")}
                  maxLength={500}
                  disabled={busy}
                />
              </Field>
            </div>
          )}

          {refused && <RefusedPanel error={refused} />}
          {forbidden && (
            <div role="status" className="rounded-lg border border-line bg-idle-soft px-4 py-3 text-sm text-ink">
              Your role can't dispatch. Sign in as owner or store.
            </div>
          )}
          {err && !shade && !refused && !forbidden && <ErrorBanner error={err} />}
        </div>
      )}
    </Modal>
  );
}

function RollPicker({
  rolls,
  selected,
  onToggle,
  showAll,
  onShowAll,
  disabled,
  error,
}: {
  rolls: RollCost[];
  selected: Set<string>;
  onToggle: (code: string) => void;
  showAll: boolean;
  onShowAll: (v: boolean) => void;
  disabled: boolean;
  error?: string;
}) {
  const ready = rolls.filter((r) => r.custody === "passed_in_store");
  const others = rolls.filter((r) => r.custody !== "passed_in_store");
  const shown = showAll ? [...ready, ...others] : ready;
  const metres = rolls.filter((r) => selected.has(r.lot_code)).reduce((s, r) => s + r.qty_m, 0);

  return (
    <fieldset className="grid gap-2">
      <legend className="mb-1 text-sm font-medium text-ink">Rolls ({count(ready.length, "roll")} passed and in store)</legend>
      {shown.length === 0 ? (
        <p className="text-sm text-muted">No rolls for this order have passed QC yet.</p>
      ) : (
        <ul className="grid max-h-48 gap-1 overflow-y-auto rounded-lg border border-line p-1 sm:max-h-64">
          {shown.map((r) => {
            const held = r.status === "quarantined" || r.status === "recalled";
            return (
              <li key={r.lot_code}>
                <label className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 hover:bg-canvas">
                  <input
                    type="checkbox"
                    className="size-4 accent-brand"
                    checked={selected.has(r.lot_code)}
                    onChange={() => onToggle(r.lot_code)}
                    disabled={disabled}
                  />
                  <span className="whitespace-nowrap font-mono text-sm text-ink">{r.lot_code}</span>
                  <span className="num text-sm text-muted">{formatQty(r.qty_m, "m")}</span>
                  <span className="ml-auto flex flex-wrap justify-end gap-1">
                    {held && <Badge tone="hold">{humanize(r.status)}</Badge>}
                    {r.custody !== "passed_in_store" && <Badge tone={custodyTone[r.custody]}>{custodyLabel[r.custody]}</Badge>}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="num text-muted">
          {count(selected.size, "roll")} · {formatQty(metres, "m")} selected
        </span>
        {others.length > 0 && (
          <label className="flex cursor-pointer items-center gap-2 text-muted">
            <input type="checkbox" className="size-4 accent-brand" checked={showAll} onChange={(e) => onShowAll(e.target.checked)} />
            Show all reserved rolls ({others.length} more)
          </label>
        )}
      </div>
      {error && <p className="text-sm text-bad">{error}</p>}
    </fieldset>
  );
}

/** Same look as the Recall page's "database refused" panel (copied, not imported). */
function RefusedPanel({ error }: { error: ApiError }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border-2 border-bad bg-bad-soft p-4 text-bad">
      <Ban className="mt-0.5 size-6 shrink-0" aria-hidden />
      <div className="grid min-w-0 gap-1">
        <p className="text-lg font-bold">The database refused</p>
        <p className="font-mono text-sm break-words">{error.message}</p>
        {error.hint && <p className="text-sm">{error.hint}</p>}
        <p className="font-mono text-xs">
          {error.code} · HTTP {error.status}
          {error.sqlstate && <> · SQLSTATE {error.sqlstate}</>}
        </p>
      </div>
    </div>
  );
}
