
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import type { MachineNow, MachineState, FloorEvent } from "@/api/types";
import { useApi, useAction } from "@/hooks/useApi";
import { machineStateTone } from "@/lib/tones";
import { formatDate, formatDateTime, formatPct } from "@/lib/format";
import {
  Badge,
  Button,
  Card,
  ErrorBanner,
  Field,
  Loadable,
  Modal,
  PageHeader,
  Select,
  StatTile,
  Textarea,
} from "@/components/ui";

const stages = [
  { value: "weaving", label: "Weaving" },
  { value: "spinning", label: "Spinning" },
  { value: "dyeing", label: "Dyeing" },
  { value: "finishing", label: "Finishing" },
] as const;

const states: { value: MachineState; label: string }[] = [
  { value: "running", label: "Running" },
  { value: "idle", label: "Idle" },
  { value: "breakdown", label: "Breakdown" },
  { value: "changeover", label: "Changeover" },
];


function elapsedSince(value: string | null) {
  if (!value) return "Time unknown";

  const startTime = new Date(value).getTime();
  const minutes = Math.max(
    0,
    Math.floor((Date.now() - startTime) / 60000),
  );

  if (minutes > 12 * 60) {
    return `since ${formatDateTime(value)}`;
  }

  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export default function FloorBoardPage() {
  const machinesState = useApi(() => api.floor.machines(), []);
  const outputState = useApi(() => api.floor.output(), []);
  const availabilityState = useApi(() => api.floor.availability(), []);

  const [machines, setMachines] = useState<MachineNow[]>([]);
  const [selected, setSelected] = useState<MachineNow | null>(null);
  const [nextState, setNextState] = useState<MachineState>("idle");
  const [reason, setReason] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [lastUpdated, setLastUpdated] = useState(Date.now());

  const changeState = useAction(
    (code: string, state: MachineState, explanation?: string) =>
      api.floor.setState(code, state, explanation),
  );

  useEffect(() => {
    if (machinesState.data) setMachines(machinesState.data);
  }, [machinesState.data]);

  const refreshMachines = useCallback(() => {
    void machinesState.reload();
    void outputState.reload();
    void availabilityState.reload();
  }, [machinesState.reload, outputState.reload, availabilityState.reload]);

  useEffect(() => {
    const unsubscribe = api.floor.subscribe((event: FloorEvent) => {
      // A state change sends two events: the old state closing (ended_at set), then the new one. Apply only the current state.
      if (event.ended_at !== null) return;
      setMachines((current) =>
        current.map((machine) =>
          machine.code === event.machine_code
            ? {
                ...machine,
                state: event.state,
                state_since: event.started_at,
                reason: event.reason,
              }
            : machine,
        ),
      );

      setLastUpdated(Date.now());

      if (event.state === "breakdown") {
        setNotice(`${event.machine_code} has reported a breakdown.`);
      }
    }, refreshMachines); // after a reconnect, re-fetch what was missed while the socket was down

    return unsubscribe;
  }, []);

  const counts = useMemo(() => ({
    running: machines.filter((m) => m.state === "running").length,
    idle: machines.filter((m) => m.state === "idle").length,
    breakdown: machines.filter((m) => m.state === "breakdown").length,
    changeover: machines.filter((m) => m.state === "changeover").length,
  }), [machines]);

  const metersToday = useMemo(() => {
    if (!outputState.data) return null;
    return outputState.data.machines.reduce((sum, item) => sum + item.meters, 0);
  }, [outputState.data]);

  const averageAvailability = useMemo(() => {
    const values = availabilityState.data?.machines
      .map((m) => m.availability_pct)
      .filter((v): v is number => v !== null && Number.isFinite(v));

    if (!values?.length) return null;
    return values.reduce((sum, value) => sum + value, 0) / values.length;
  }, [availabilityState.data]);

  async function submitStateChange() {
    if (!selected) return;

    setActionError(null);
    setNotice("");

    const result = await changeState.run(
      selected.code,
      nextState,
      reason.trim() || undefined,
    );

    if (!result) {
      setActionError("The machine state could not be changed. Please try again.");
      return;
    }

    setMachines((current) =>
      current.map((machine) =>
        machine.code === selected.code
          ? {
              ...machine,
              state: result.state,
              state_since: result.started_at,
              reason: reason.trim() || null,
            }
          : machine,
      ),
    );

    setNotice(`${selected.name} is now ${result.state}.`);
    setSelected(null);
    setReason("");
    setLastUpdated(Date.now());
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Floor Board"
        subtitle="Live production-floor status across spinning, weaving, dyeing and finishing."
        actions={
          <Button
            variant="secondary"
            onClick={refreshMachines}
            loading={
              machinesState.loading ||
              outputState.loading ||
              availabilityState.loading
            }
          >
            Refresh data
          </Button>
        }
      />

      {notice && (
        <div
          role="status"
          className="rounded-lg border border-line bg-surface px-4 py-3 text-sm text-ink"
        >
          {notice}
          <button
            className="ml-3 font-medium underline"
            onClick={() => setNotice("")}
          >
            Dismiss
          </button>
        </div>
      )}

      {machinesState.error && (
        <ErrorBanner error={machinesState.error} onRetry={refreshMachines} />
      )}

      <Loadable state={machinesState}>
        {() => (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
              <StatTile label="Machines running" value={counts.running} tone="ok" />
              <StatTile label="Idle" value={counts.idle} tone="idle" />
              <StatTile label="Breakdowns" value={counts.breakdown} tone="bad" />
              <StatTile label="Metres produced today" value={metersToday === null ? "—" : metersToday.toLocaleString()} hint={outputState.data?.day ? formatDate(outputState.data.day) : "Production date"} tone="brand" />
              <StatTile label="30-day availability" value={averageAvailability === null ? "—" : formatPct(averageAvailability)} hint={availabilityState.data ? `${formatDate(availabilityState.data.from)} – ${formatDate(availabilityState.data.to)}` : "Loading availability"} tone="accent" />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted">
              <span>{machines.length} machines · {counts.changeover} in changeover</span>
              <span>Updated {formatDateTime(new Date(lastUpdated).toISOString())}</span>
            </div>

            {stages.map((stage) => {
              const stageMachines = machines.filter((m) => m.stage === stage.value);
              if (!stageMachines.length) return null;

              return (
                <section key={stage.value} className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h2 className="text-base font-semibold text-ink">{stage.label}</h2>
                    <span className="text-sm text-muted">{stageMachines.length} machines</span>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                    {stageMachines.map((machine) => (
                      <Card
                        key={machine.code}
                        className={
                          machine.state === "breakdown"
                            ? "border-bad/50"
                            : undefined
                        }
                        title={
                          <div className="flex flex-wrap items-center gap-2">
                            <span>{machine.name}</span>
                            <Badge tone={machineStateTone[machine.state]}>
                              {titleCase(machine.state)}
                            </Badge>
                          </div>
                        }
                        subtitle={machine.code}
                        actions={
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => {
                              setSelected(machine);
                              setNextState(machine.state);
                              setReason(machine.reason ?? "");
                              setActionError(null);
                            }}
                          >
                            Change state
                          </Button>
                        }
                      >
                        <div className="space-y-3 text-sm">
                          <div className="flex justify-between gap-3">
                            <span className="text-muted">Current state since</span>
                            <span className="num text-right">{elapsedSince(machine.state_since)}</span>
                          </div>
                          <div className="flex justify-between gap-3">
                            <span className="text-muted">Current lot</span>
                            <span className="text-right font-medium">{machine.current_lot ?? "—"}</span>
                          </div>
                          <div className="flex justify-between gap-3">
                            <span className="text-muted">Order</span>
                            <span className="text-right">{machine.current_order ?? "—"}</span>
                          </div>
                          <div className="flex justify-between gap-3">
                            <span className="text-muted">Run</span>
                            <span className="text-right">{machine.current_run ?? "—"}</span>
                          </div>
                          {machine.reason && (
                            <p className="rounded-lg bg-canvas px-3 py-2 text-muted">
                              Reason: {machine.reason}
                            </p>
                          )}
                        </div>
                      </Card>
                    ))}
                  </div>
                </section>
              );
            })}
          </>
        )}
      </Loadable>

      <Modal
        open={selected !== null}
        onClose={() => {
          if (!changeState.running) setSelected(null);
        }}
        title={selected ? `Change state · ${selected.name}` : "Change machine state"}
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setSelected(null)}
              disabled={changeState.running}
            >
              Cancel
            </Button>
            <Button onClick={() => void submitStateChange()} loading={changeState.running}>
              Save state
            </Button>
          </>
        }
      >
        {selected && (
          <div className="space-y-4">
            <p className="text-sm text-muted">
              Update the state for {selected.code}. The change will be reflected on this board.
            </p>
            <Field label="New state">
              <Select
                value={nextState}
                onChange={(event) => setNextState(event.target.value as MachineState)}
                disabled={changeState.running}
              >
                {states.map((state) => (
                  <option key={state.value} value={state.value}>
                    {state.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Reason (optional)" hint="Add a short note for the floor team.">
              <Textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="e.g. Scheduled maintenance"
                rows={3}
                disabled={changeState.running}
              />
            </Field>
            {actionError && (
              <p role="alert" className="text-sm text-bad">{actionError}</p>
            )}
            {changeState.error && <ErrorBanner error={changeState.error} />}
          </div>
        )}
      </Modal>
    </div>
  );
}