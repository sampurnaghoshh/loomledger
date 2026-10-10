// TODO(Adithi): replace this placeholder with the real page. Keep the default export name.
import { api } from "@/api/client";
import { TodoPage } from "./_TodoPage";

export default function InventoryPage() {
  return (
    <TodoPage
      title="Inventory"
      owner="Adithi"
      load={() => api.inventory.stock()}
      build={
        <ul className="list-disc space-y-1 pl-5">
          <li>{"Stock table grouped by location (Yarn Store, Greige Store, FG Store, Reject Bay, Quarantine Cage): lot, product, qty + unit."}</li>
          <li>{"Filter chips by lot kind (yarn / greige / finished). Quarantine rows use the 'hold' tone."}</li>
          <li>{"TIME TRAVEL: an 'As of' date-time picker + slider over the last 21 days → api.inventory.stock(asOfIso). Show 'Viewing stock as of 20 Sep, 10:45' banner with a 'Back to now' button."}</li>
        </ul>
      }
    />
  );
}
