// TODO(Dhruva): replace with the real buyer page. PUBLIC (no login), MOBILE FIRST (design at 375px wide).
// Try: /track/4155711b-d0c4-5f02-a2b5-bfd8dd09045d (SO-0412)  ·  /track/not-a-token (404 state)
import { useParams } from "react-router-dom";
import { api } from "@/api/client";
import { Card, Loadable } from "@/components/ui";
import { useApi } from "@/hooks/useApi";

export default function TrackPage() {
  const { token = "" } = useParams();
  const state = useApi(() => api.orders.track(token), [token]);
  return (
    <div className="mx-auto max-w-md p-4">
      <Card title="Order tracking (placeholder)" subtitle="Owner: Dhruva · see docs/TEAM_PLAN.md">
        <ul className="mb-4 list-disc space-y-1 pl-5 text-sm">
          <li>Header: mill name, order code, buyer, product.</li>
          <li>Big 'Expected dispatch' date; if delayed: amber banner 'Was 14 Oct, now 16 Oct' with the reason from updates.</li>
          <li>Progress: dispatched / ready / quality check / weaving / on hold, as a segmented bar with metres.</li>
          <li>Updates timeline (newest first), formatted with formatDateTime.</li>
          <li>Invalid/expired token: friendly 'This tracking link is invalid or has expired' card (error.code === 'NOT_FOUND').</li>
        </ul>
        <Loadable state={state}>
          {(data) => <pre className="overflow-auto rounded-lg bg-canvas p-3 font-mono text-xs">{JSON.stringify(data, null, 2)}</pre>}
        </Loadable>
      </Card>
    </div>
  );
}
