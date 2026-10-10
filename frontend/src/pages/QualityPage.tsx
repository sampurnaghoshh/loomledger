// TODO(Adithi): replace this placeholder with the real page. Keep the default export name.
import { api } from "@/api/client";
import { TodoPage } from "./_TodoPage";

export default function QualityPage() {
  return (
    <TodoPage
      title="Quality"
      owner="Adithi"
      load={() => api.quality.queue()}
      build={
        <ul className="list-disc space-y-1 pl-5">
          <li>{"Alert strip at top when there are rejections today (api.quality.rejections): '3 rolls rejected for colour mismatch' + button 'Find cause' → navigate('/trace?lots=R-1201,R-1202,R-1203')."}</li>
          <li>{"QC queue table (awaiting inspection): roll, product, dye batch, dyed on, order. Row click → Modal: Pass / Rework / Reject; defect type + metres required when not Pass → api.quality.inspect."}</li>
          <li>{"Recent rejections table below (roll, defect, inspector, time, order)."}</li>
        </ul>
      }
    />
  );
}
