// Low-yarn warning (migration 014 v_yarn_low_stock): free yarn = usable on hand − what open orders still need.
// <LowStockBanner> explains it on Inventory; <LowStockBadge> is the compact link on the Floor Board.
// Nothing is shown when no yarn is below its reorder level.
import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { api } from "@/api/client";
import type { LowStock } from "@/api/types";
import { Loadable } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { formatQty } from "@/lib/format";

function useLowStock() {
  return useApi(() => api.inventory.lowStock(), []);
}

function LowStockLine({ y }: { y: LowStock }) {
  const free =
    y.available_kg < 0
      ? `the open orders need ${formatQty(-y.available_kg, "kg")} more than we have`
      : `only ${formatQty(y.available_kg, "kg")} is free`;
  return (
    <li>
      <p className="font-medium text-ink">
        {y.product_name} <span className="font-mono text-muted">{y.product_code}</span>: {free}. Reorder at least{" "}
        {formatQty(y.below_reorder_kg, "kg")}.
      </p>
      <p className="num text-muted">
        {formatQty(y.on_hand_kg, "kg")} usable in the yarn store − {formatQty(y.committed_kg, "kg")} still to weave for{" "}
        {y.open_orders} open order{y.open_orders === 1 ? "" : "s"} · reorder level {formatQty(y.reorder_level_kg, "kg")}
        {y.quarantined_kg > 0 && <> · {formatQty(y.quarantined_kg, "kg")} quarantined, not counted</>}
      </p>
    </li>
  );
}

export function LowStockBanner() {
  const low = useLowStock();
  return (
    <Loadable state={low}>
      {(rows) =>
        rows.length === 0 ? null : (
          <div role="status" className="flex gap-3 rounded-xl border border-warn bg-warn-soft px-4 py-3 text-sm">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-warn" aria-hidden />
            <div className="grid gap-2">
              <p className="font-semibold text-ink">Yarn is running low</p>
              <ul className="grid gap-2">
                {rows.map((y) => (
                  <LowStockLine key={y.product_code} y={y} />
                ))}
              </ul>
              <p className="text-muted">
                <Link to="/orders" className="font-medium text-brand underline">See which orders are short</Link>
              </p>
            </div>
          </div>
        )
      }
    </Loadable>
  );
}

export function LowStockBadge() {
  const low = useLowStock();
  const rows = low.data ?? [];
  if (low.error || rows.length === 0) return null; // the badge is a nudge; Inventory shows the details and errors
  const worst = rows[0];
  return (
    <Link
      to="/inventory"
      className="inline-flex items-center gap-2 rounded-full border border-warn bg-warn-soft px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface"
    >
      <AlertTriangle className="size-4 text-warn" aria-hidden />
      Yarn low{rows.length > 1 ? ` (${rows.length})` : ""}: reorder {formatQty(worst.below_reorder_kg, "kg")}
    </Link>
  );
}
