// TODO(Dhruva): replace this placeholder with the real page. Keep the default export name.
import { api } from "@/api/client";
import { TodoPage } from "./_TodoPage";

export default function MonthEndPage() {
  return (
    <TodoPage
      title="Month-end"
      owner="Dhruva"
      load={() => api.finance.massBalance()}
      build={
        <ul className="list-disc space-y-1 pl-5">
          <li>{"Mass balance tiles: received, issued, fabric, waste, on loom, UNACCOUNTED (kg and %). Formula note: kg = m × width × GSM / 1000."}</li>
          <li>{"Stacked bar (recharts) of issued yarn = fabric + waste + on loom + unaccounted; table by machine with Loom 3 highlighted (6.64%)."}</li>
          <li>{"True cost per roll: order picker → api.finance.rollCosts(order) → table + stacked bar (material, machine, labour, chemicals), total and ₹/m."}</li>
        </ul>
      }
    />
  );
}
