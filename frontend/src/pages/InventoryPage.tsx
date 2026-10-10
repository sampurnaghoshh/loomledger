
import { useMemo, useState } from "react";
import { api } from "@/api/client";
import type { LotKind, StockRow } from "@/api/types";
import { useApi } from "@/hooks/useApi";
import { formatDateTime, formatQty } from "@/lib/format";
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  Loadable,
  PageHeader,
} from "@/components/ui";

const DAY_MS = 24 * 60 * 60 * 1000;
const LOCATION_ORDER = [
  "YARN-STORE",
  "GREIGE-STORE",
  "FG-STORE",
  "REJECT-BAY",
  "QUARANTINE-CAGE",
];

const LOCATION_NAMES: Record<string, string> = {
  "YARN-STORE": "Yarn Store",
  "GREIGE-STORE": "Greige Store",
  "FG-STORE": "Finished Goods Store",
  "REJECT-BAY": "Reject Bay",
  "QUARANTINE-CAGE": "Quarantine Cage",
};

const FILTERS: { label: string; value: LotKind | "all" }[] = [
  { label: "All stock", value: "all" },
  { label: "Yarn", value: "yarn" },
  { label: "Greige", value: "greige" },
  { label: "Finished", value: "finished" },
];

function toLocalInputValue(timestamp: number) {
  const date = new Date(timestamp);
  const localDate = new Date(
    timestamp - date.getTimezoneOffset() * 60_000,
  );
  return localDate.toISOString().slice(0, 16);
}
function locationName(code: string) {
  return (
    LOCATION_NAMES[code] ??
    code
      .toLowerCase()
      .split("-")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ")
  );
}

function isQuarantine(row: StockRow) {
  return (
    row.location_code.toUpperCase().includes("QUARANTINE") ||
    row.location_code.toUpperCase().includes("HOLD")
  );
}

export default function InventoryPage() {
  const [filter, setFilter] = useState<LotKind | "all">("all");
  const [now] = useState(() => Date.now());
  const [selectedTime, setSelectedTime] = useState(() => Date.now());
  const [requestAsOf, setRequestAsOf] = useState<string | null>(null);

  const stockState = useApi(
    () => api.inventory.stock(requestAsOf ?? undefined),
    [requestAsOf],
  );

  const minTime = now - 21 * DAY_MS;

  const rows = useMemo(() => {
    const stockRows = stockState.data?.rows ?? [];
    return filter === "all"
      ? stockRows
      : stockRows.filter((row) => row.lot_kind === filter);
  }, [stockState.data, filter]);

  const groupedRows = useMemo(() => {
    const groups = new Map<string, StockRow[]>();

    for (const row of rows) {
      const group = groups.get(row.location_code) ?? [];
      group.push(row);
      groups.set(row.location_code, group);
    }

    return [...groups.entries()].sort(([a], [b]) => {
      const aIndex = LOCATION_ORDER.indexOf(a.toUpperCase());
      const bIndex = LOCATION_ORDER.indexOf(b.toUpperCase());
      return (aIndex < 0 ? 999 : aIndex) - (bIndex < 0 ? 999 : bIndex);
    });
  }, [rows]);

  const isHistorical = Boolean(stockState.data?.as_of);

  function viewSelectedTime() {
    setRequestAsOf(new Date(selectedTime).toISOString());
  }

  function backToNow() {
    setSelectedTime(Date.now());
    setRequestAsOf(null);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Inventory"
        subtitle="Stock across stores, work in progress and quarantined material."
        actions={
          <Button
            variant="secondary"
            onClick={() => void stockState.reload()}
            loading={stockState.loading}
          >
            Refresh stock
          </Button>
        }
      />

      <Card
        title="Stock time travel"
        subtitle="Inspect the inventory snapshot at a point in the last 21 days."
      >
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="As of date and time">
              <Input
                type="datetime-local"
                value={toLocalInputValue(selectedTime)}
                onChange={(event) => {
                  const value = new Date(event.target.value).getTime();
                  if (
                    Number.isFinite(value) &&
                    value >= minTime &&
                    value <= now
                  ) {
                    setSelectedTime(value);
                  }
                }}
              />
            </Field>

            <div className="flex flex-wrap items-end gap-2">
              <Button
                onClick={viewSelectedTime}
                disabled={selectedTime < minTime || selectedTime > now}
                loading={stockState.loading}
              >
                View this time
              </Button>
              {isHistorical && (
                <Button variant="secondary" onClick={backToNow}>
                  Back to now
                </Button>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="text-muted">21 days ago</span>
              <span className="font-medium text-ink">
                {formatDateTime(new Date(selectedTime).toISOString())}
              </span>
              <span className="text-muted">Now</span>
            </div>
            <input
              aria-label="Choose inventory time within the last 21 days"
              type="range"
              min={minTime}
              max={now}
              step={15 * 60 * 1000}
              value={Math.min(now, Math.max(minTime, selectedTime))}
              onChange={(event) =>
                setSelectedTime(Number(event.target.value))
              }
              className="w-full accent-[var(--color-brand)]"
            />
            <p className="text-xs text-muted">
              Move the slider, then select “View this time” to load that
              snapshot. Future times are not available.
            </p>
          </div>
        </div>
      </Card>

      {isHistorical && (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface px-4 py-3 text-sm"
        >
          <span>
            Viewing stock as of{" "}
            <strong>{formatDateTime(stockState.data!.as_of!)}</strong>
          </span>
          <Button variant="secondary" size="sm" onClick={backToNow}>
            Back to now
          </Button>
        </div>
      )}
      <Loadable state={stockState}>
        {() => (
          <Card title="Stock overview" subtitle={`${rows.length} stock entries`}>
        <div className="mb-5 flex flex-wrap gap-2">
          {FILTERS.map((item) => {
            const active = filter === item.value;

            return (
              <button
                key={item.value}
                type="button"
                onClick={() => setFilter(item.value)}
                aria-pressed={active}
                className={`rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
                  active
                    ? "border-brand bg-brand text-white"
                    : "border-line bg-surface text-ink hover:bg-canvas"
                }`}
              >
                {item.label}
              </button>
            );
          })}
        </div>

        {groupedRows.length === 0 ? (
          <div className="py-10 text-center">
            <p className="font-medium text-ink">No stock entries found</p>
            <p className="mt-1 text-sm text-muted">
              Try another stock filter or select a different time.
            </p>
          </div>
        ) : (
          <div className="space-y-6">
            {groupedRows.map(([location, locationRows]) => (
              <section key={location} className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-base font-semibold text-ink">
                    {locationName(location)}
                  </h2>
                  <span className="text-sm text-muted">
                    {locationRows.length} entries
                  </span>
                </div>

                <div className="overflow-x-auto rounded-lg border border-line">
                  <table className="w-full min-w-[620px] text-left text-sm">
                    <thead className="bg-canvas text-muted">
                      <tr>
                        <th className="px-4 py-3 font-medium">Lot</th>
                        <th className="px-4 py-3 font-medium">Product</th>
                        <th className="px-4 py-3 font-medium">Kind</th>
                        <th className="px-4 py-3 text-right font-medium">
                          Quantity
                        </th>
                        <th className="px-4 py-3 font-medium">Unit</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {locationRows.map((row, index) => (
                        <tr
                          key={`${row.location_code}-${row.lot_code}-${index}`}
                          className={
                            isQuarantine(row)
                              ? "bg-hold-soft"
                              : "bg-surface"
                          }
                        >
                          <td className="px-4 py-3 font-medium text-ink">
                            {row.lot_code}
                          </td>
                          <td className="px-4 py-3 text-ink">
                            {row.product_code}
                          </td>
                          <td className="px-4 py-3">
                            <Badge
                              tone={isQuarantine(row) ? "hold" : "idle"}
                            >
                              {row.lot_kind}
                            </Badge>
                            {isQuarantine(row) && (
                              <span className="ml-2">
                                <Badge tone="hold">On hold</Badge>
                              </span>
                            )}
                          </td>
                          <td className="num px-4 py-3 text-right text-ink">
                            {formatQty(row.qty, row.uom).replace(` ${row.uom}`, "")}
                          </td>
                          <td className="px-4 py-3 text-muted">{row.uom}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </div>
        )}
          </Card>
        )}
      </Loadable>
    </div>
  );
}