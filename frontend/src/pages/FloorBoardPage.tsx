// TODO(Adithi): replace this placeholder with the real page. Keep the default export name.
import { api } from "@/api/client";
import { TodoPage } from "./_TodoPage";

export default function FloorBoardPage() {
  return (
    <TodoPage
      title="Floor Board"
      owner="Adithi"
      load={() => api.floor.machines()}
      build={
        <ul className="list-disc space-y-1 pl-5">
          <li>{"Stat tiles: machines running / idle / breakdown, metres produced today (api.floor.output), 30-day availability (api.floor.availability)."}</li>
          <li>{"Grid of machine cards grouped by stage (weaving, dyeing, spinning): name, state Badge (machineStateTone), 'since 3h 20m', current lot + order."}</li>
          <li>{"Live: api.floor.subscribe(event => update that machine's state) and show a short banner when a machine breaks down."}</li>
          <li>{"Supervisor action on a card: 'Change state' → Modal → api.floor.setState(code, state, reason)."}</li>
        </ul>
      }
    />
  );
}
