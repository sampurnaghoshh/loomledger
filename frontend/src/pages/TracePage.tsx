// TODO(Nooman): replace this placeholder with the real page. Keep the default export name.
import { api } from "@/api/client";
import { TodoPage } from "./_TodoPage";

export default function TracePage() {
  return (
    <TodoPage
      title="Find Cause"
      owner="Nooman"
      load={() => api.trace.findCause(['R-1201','R-1202','R-1203'])}
      build={
        <ul className="list-disc space-y-1 pl-5">
          <li>{"Read ?lots= from the URL (default R-1201,R-1202,R-1203); chips for the selected rejected rolls."}</li>
          <li>{"Ranked factor table: label, covers 3/3, bad/inspected through it, rate through vs elsewhere (two bars), lift, verdict Badge (verdictTone/verdictLabel)."}</li>
          <li>{"Headline card for factors[0]: 'Yarn Lot Y-112 — 37.5% defect rate vs 4.0% elsewhere (9.4×)'. One-line explanation of why Dye Vat 3 is coincidental."}</li>
          <li>{"Genealogy graph from api.trace.ancestors(lots): yarn → greige roll → finished roll, machine + shift on each node, root cause highlighted."}</li>
          <li>{"CTA 'Recall Yarn Lot Y-112' → /recall/Y-112."}</li>
        </ul>
      }
    />
  );
}
