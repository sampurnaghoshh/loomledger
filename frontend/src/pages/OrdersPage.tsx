
import { api } from "@/api/client";
import type { OrderSummary, OrderProgress } from "@/api/types";
import { useApi } from "@/hooks/useApi";
import { Loadable } from "@/components/ui";
import { formatDate, formatQty } from "@/lib/format";

const stages: {
  key: keyof OrderProgress;
  label: string;
  color: string;
}[] = [
  { key: "dispatched_m", label: "Dispatched", color: "bg-emerald-500" },
  { key: "ready_m", label: "Ready", color: "bg-blue-500" },
  { key: "quality_check_m", label: "Quality check", color: "bg-violet-500" },
  { key: "weaving_m", label: "Weaving", color: "bg-amber-500" },
  { key: "on_hold_m", label: "On hold", color: "bg-red-500" },
];

function ProgressBar({ order }: { order: OrderSummary }) {
  return (
    <div>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-gray-200">
        {stages.map((stage) => (
          <div
            key={stage.key}
            className={stage.color}
            style={{
              width: `${
                (order.progress[stage.key] / order.ordered_m) * 100
              }%`,
            }}
          />
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-3 text-xs">
        {stages.map((stage) => (
          <div key={stage.key} className="flex items-center gap-1">
            <span className={`h-2 w-2 rounded-full ${stage.color}`} />
            <span>
              {stage.label}: {formatQty(order.progress[stage.key], "m")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function OrderCard({ order }: { order: OrderSummary }) {
  const expectedDate =
    order.revised_promise_date ?? order.promised_date;

  const delayed =
    new Date(expectedDate).getTime() >
    new Date(order.promised_date).getTime();

  const trackingUrl = `${window.location.origin}/track/${order.tracking_token}`;

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(trackingUrl);
      alert("Buyer tracking link copied!");
    } catch {
      alert("Could not copy the link.");
    }
  };

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-mono text-xl font-bold text-gray-900">
          {order.code}
        </h2>

        <span className="rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-800">
          {order.status.replace(/_/g, " ")}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
        <div>
          <p className="text-gray-500">Buyer</p>
          <p className="font-semibold text-gray-900">{order.buyer}</p>
        </div>

        <div>
          <p className="text-gray-500">Product</p>
          <p className="font-semibold text-gray-900">{order.product}</p>
        </div>

        <div>
          <p className="text-gray-500">Quantity</p>
          <p className="font-semibold text-gray-900">
            {formatQty(order.ordered_m, "m")}
          </p>
        </div>

        <div>
          <p className="text-gray-500">Promised date</p>
          <p className="font-semibold text-gray-900">
            {formatDate(order.promised_date)}
          </p>
        </div>

        <div className="col-span-2">
          <p className="text-gray-500">Expected dispatch</p>
          <p
            className={`text-lg font-bold ${
              delayed ? "text-red-600" : "text-gray-900"
            }`}
          >
            {formatDate(expectedDate)}
          </p>
          {delayed && (
            <p className="text-xs text-red-600">
              Revised from {formatDate(order.promised_date)}
            </p>
          )}
        </div>
      </div>

      <div className="mt-5">
        <h3 className="mb-3 text-sm font-semibold text-gray-900">
          Production progress
        </h3>
        <ProgressBar order={order} />
      </div>

      <div className="mt-5 flex flex-wrap gap-3">
        <a
          href={trackingUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800"
        >
          Buyer link ↗
        </a>

        <button
          type="button"
          onClick={copyLink}
          className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-800 hover:bg-gray-100"
        >
          Copy link
        </button>
      </div>
    </div>
  );
}

export default function OrdersPage() {
  const state = useApi(() => api.orders.list(), []);

  return (
    <main className="mx-auto max-w-6xl p-4 sm:p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">
          Orders
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Track customer orders, dispatch dates and production progress.
        </p>
      </div>

      <Loadable state={state}>
        {(orders) => (
          <div className="grid gap-5 lg:grid-cols-2">
            {orders.map((order) => (
              <OrderCard key={order.code} order={order} />
            ))}
          </div>
        )}
      </Loadable>
    </main>
  );
}
