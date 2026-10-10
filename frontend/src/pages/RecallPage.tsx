// TODO(Nooman): replace this placeholder with the real page. Keep the default export name.
import { api } from "@/api/client";
import { TodoPage } from "./_TodoPage";

export default function RecallPage() {
  return (
    <TodoPage
      title="Recall"
      owner="Nooman"
      load={() => api.recalls.preview('Y-112')}
      build={
        <ul className="list-disc space-y-1 pl-5">
          <li>{"Impact panel (StatTiles): rolls affected 12 (3 rejected + 9 at risk), orders 2, buyers 2 (1 holding goods), remake 600 m, delay 3 days, money split: already lost / newly exposed / recoverable / total."}</li>
          <li>{"Calculation line under the delay: response.calculation.display ('600 ÷ 250 = 2.4 → ceil = 3 working days')."}</li>
          <li>{"Rolls table by custody (custodyTone/custodyLabel) with cost; orders table promised → revised date."}</li>
          <li>{"'Apply recall' → confirm Modal → api.recalls.apply(lot, reason) → page switches to applied state (Badge 'Quarantined')."}</li>
          <li>{"'Try issuing Y-112 to Loom 2' button → api.production.startWeaving(...) → shows the LOT_QUARANTINED ErrorBanner (the database refused)."}</li>
        </ul>
      }
    />
  );
}
