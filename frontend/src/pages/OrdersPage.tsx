// TODO(Dhruva): replace this placeholder with the real page. Keep the default export name.
import { api } from "@/api/client";
import { TodoPage } from "./_TodoPage";

export default function OrdersPage() {
  return (
    <TodoPage
      title="Orders"
      owner="Dhruva"
      load={() => api.orders.list()}
      build={
        <ul className="list-disc space-y-1 pl-5">
          <li>{"Orders table: code, buyer, product, ordered m, promised date, expected date (revised in 'bad' tone when later), status Badge."}</li>
          <li>{"Progress bar per order from progress: dispatched / ready / quality check / weaving / on hold (segments in tone colours) with a legend."}</li>
          <li>{"'Buyer link' button per order → opens /track/<tracking_token> in a new tab; 'Copy link' copies the full URL."}</li>
        </ul>
      }
    />
  );
}
