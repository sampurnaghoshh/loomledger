// TODO(Adithi): replace this placeholder with the real page. Keep the default export name.
import { api } from "@/api/client";
import { TodoPage } from "./_TodoPage";

export default function GateEntryPage() {
  return (
    <TodoPage
      title="Gate Entry"
      owner="Adithi"
      load={() => api.inventory.stock()}
      build={
        <ul className="list-disc space-y-1 pl-5">
          <li>{"Yarn receipt form: supplier (SUP-KAV Kaveri Yarn Traders / SUP-NAR Narmada Spinners), lot code, kg, ₹ per kg, vehicle no., challan no."}</li>
          <li>{"Validate inline (required, kg > 0, price > 0, lot code like Y-113). Send idempotency_key = newIdempotencyKey() created once per form."}</li>
          <li>{"On success: green confirmation card with receipt code and 'Record another'. On error: ErrorBanner with the API message."}</li>
        </ul>
      }
    />
  );
}
