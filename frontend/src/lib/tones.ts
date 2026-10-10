// One mapping from domain states to colour tones, so every screen agrees.
import type { Custody, LotStatus, MachineState, Verdict } from "@/api/types";

export type Tone = "ok" | "warn" | "bad" | "hold" | "brand" | "accent" | "idle";

export const machineStateTone: Record<MachineState, Tone> = {
  running: "ok",
  idle: "idle",
  breakdown: "bad",
  changeover: "warn",
};

export const custodyTone: Record<Custody, Tone> = {
  passed_in_store: "ok",
  awaiting_qc: "warn",
  rework: "warn",
  rejected: "bad",
  wip: "brand",
  at_customer: "accent",
  consumed: "idle",
};

export const custodyLabel: Record<Custody, string> = {
  passed_in_store: "Passed, in store",
  awaiting_qc: "Awaiting QC",
  rework: "Rework",
  rejected: "Rejected",
  wip: "On the loom",
  at_customer: "At customer",
  consumed: "Consumed",
};

export const lotStatusTone: Record<LotStatus, Tone> = {
  active: "ok",
  wip: "brand",
  consumed: "idle",
  dispatched: "accent",
  quarantined: "hold",
  recalled: "hold",
};

export const verdictTone: Record<Verdict, Tone> = {
  root_cause: "bad",
  coincidental: "idle",
  partial: "warn",
  no_comparison: "idle",
};

export const verdictLabel: Record<Verdict, string> = {
  root_cause: "Root cause",
  coincidental: "Coincidental",
  partial: "Partial — doesn't explain every roll",
  no_comparison: "No comparison group",
};
