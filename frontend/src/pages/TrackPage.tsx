
import { useParams } from "react-router-dom";
import { AlertTriangle, CalendarDays, Package, Clock3 } from "lucide-react";
import { api } from "@/api/client";
import type { BuyerOrderStatus, OrderProgress } from "@/api/types";
import { Badge, Card, Loadable } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { formatDate, formatDateTime, formatQty } from "@/lib/format";

const stages: {
  key: keyof OrderProgress;
  label: string;
  color: string;
}[] = [
  { key: "dispatched_m", label: "Dispatched", color: "bg-ok" },
  { key: "ready_m", label: "Ready", color: "bg-brand" },
  { key: "quality_check_m", label: "Quality check", color: "bg-accent" },
  { key: "weaving_m", label: "Weaving", color: "bg-warn" },
  { key: "on_hold_m", label: "On hold", color: "bg-hold" },
];

function TrackingDetails({ data }: { data: BuyerOrderStatus }) {
  const ordered = Math.max(0, data.ordered_m);
  const totalProgress = stages.reduce(
    (sum, stage) => sum + Math.max(0, data.progress[stage.key]),
    0
  );

  const updates = [...data.updates].sort(
    (a, b) => new Date(b.at).getTime() - new Date(a.at).getTime()
  );

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">
              Order tracking
            </p>
            <h1 className="mt-2 break-words font-mono text-2xl font-bold text-ink">
              {data.order}
            </h1>
          </div>
          <Badge tone={data.delayed ? "warn" : "ok"}>
            {data.delayed ? "Delayed" : "On schedule"}
          </Badge>
        </div>

        <div className="mt-5 space-y-3 border-t border-line pt-4 text-sm">
          <div className="flex items-start gap-3">
            <Package className="mt-0.5 size-4 shrink-0 text-muted" />
            <div>
              <p className="text-xs text-muted">Buyer</p>
              <p className="font-medium text-ink">{data.buyer}</p>
            </div>
          </div>
          <div>
            <p className="text-xs text-muted">Product</p>
            <p className="font-medium text-ink">{data.product}</p>
          </div>
          <div>
            <p className="text-xs text-muted">Quantity ordered</p>
            <p className="font-medium text-ink">
              {formatQty(data.ordered_m, "m")}
            </p>
          </div>
        </div>
      </Card>

      <Card>
        <div className="flex items-center gap-2 text-muted">
          <CalendarDays className="size-4" />
          <p className="text-xs font-semibold uppercase tracking-wide">
            Expected dispatch
          </p>
        </div>

        <p className="mt-3 text-3xl font-bold tracking-tight text-ink">
          {formatDate(data.expected_date)}
        </p>

        {data.delayed && (
          <div
            role="status"
            className="mt-4 rounded-lg border border-warn/30 bg-warn-soft p-4"
          >
            <div className="flex items-center gap-2 font-semibold text-warn">
              <AlertTriangle className="size-4 shrink-0" />
              Dispatch delayed
            </div>
            <p className="mt-2 text-sm text-ink">
              Was {formatDate(data.promised_date)}, now{" "}
              {formatDate(data.expected_date)}.
            </p>
            {updates.length > 0 && (
              <p className="mt-2 text-sm text-muted">
                {updates[0].message}
              </p>
            )}
          </div>
        )}
      </Card>

      <Card title="Production progress" subtitle={`${formatQty(ordered, "m")} ordered`}>
        <div
          className="flex h-4 w-full overflow-hidden rounded-full bg-canvas"
          role="img"
          aria-label={`Production progress: ${formatQty(totalProgress, "m")} accounted for out of ${formatQty(ordered, "m")} ordered`}
        >
          {ordered > 0 &&
            stages.map((stage) => {
              const value = Math.max(0, data.progress[stage.key]);
              return (
                <div
                  key={stage.key}
                  className={stage.color}
                  style={{
                    width: `${(value / Math.max(ordered, totalProgress)) * 100}%`,
                  }}
                  title={`${stage.label}: ${formatQty(value, "m")}`}
                />
              );
            })}
        </div>

        <p className="mt-2 text-right text-xs text-muted">
          {formatQty(totalProgress, "m")} accounted for
        </p>

        <div className="mt-5 space-y-3">
          {stages.map((stage) => (
            <div
              key={stage.key}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <div className="flex min-w-0 items-center gap-2">
                <span className={`size-3 shrink-0 rounded-sm ${stage.color}`} />
                <span className="text-muted">{stage.label}</span>
              </div>
              <span className="shrink-0 font-medium text-ink">
                {formatQty(data.progress[stage.key], "m")}
              </span>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Updates" subtitle="Latest order activity">
        {updates.length === 0 ? (
          <p className="text-sm text-muted">No updates available yet.</p>
        ) : (
          <ol className="space-y-5">
            {updates.map((update, index) => (
              <li key={`${update.at}-${index}`} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <span className="mt-1.5 size-2.5 shrink-0 rounded-full bg-brand" />
                  {index < updates.length - 1 && (
                    <span className="mt-2 w-px flex-1 bg-line" />
                  )}
                </div>
                <div className="min-w-0 flex-1 pb-2">
                  <p className="flex items-center gap-1.5 text-xs text-muted">
                    <Clock3 className="size-3" />
                    {formatDateTime(update.at)}
                  </p>
                  <p className="mt-1 break-words text-sm leading-relaxed text-ink">
                    {update.message}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}

export default function TrackPage() {
  const { token = "" } = useParams();
  const state = useApi(() => api.orders.track(token), [token]);

  return (
    <main className="min-h-screen bg-canvas px-4 py-6">
      <div className="mx-auto w-full max-w-md">
        <header className="mb-6 text-center">
          <p className="text-sm font-semibold tracking-wide text-brand">
            Everest Textile Mills
          </p>
          <p className="mt-1 text-xs text-muted">
            Buyer order tracking
          </p>
        </header>

        {state.error?.code === "NOT_FOUND" ? (
          <Card>
            <div className="py-8 text-center">
              <Package className="mx-auto mb-4 size-10 text-muted" />
              <h1 className="text-xl font-semibold text-ink">
                This tracking link is invalid or has expired
              </h1>
              <p className="mt-3 text-sm text-muted">
                Please contact Everest Textile Mills for a new tracking link.
              </p>
            </div>
          </Card>
        ) : (
          <Loadable state={state}>
            {(data) => <TrackingDetails data={data} />}
          </Loadable>
        )}
      </div>
    </main>
  );
}
