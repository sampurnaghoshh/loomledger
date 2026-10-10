// One mapping from domain states to colour tones, so every screen agrees.
import type { Custody, LotStatus, MachineState, RollPassport, Verdict } from "@/api/types";

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

/** Run progress bar on the Floor Board. A roll woven to plan (due off the loom) is information, not an alarm: neutral,
 * like a stopped machine's bar, so a live breakdown stays the loudest thing on the board. */
export function runProgressTone(run: { woven_to_plan_at: string | null }, stopped: boolean): "brand" | "idle" {
  return run.woven_to_plan_at !== null || stopped ? "idle" : "brand";
}

/** The big banner on a roll's QR passport: a recall freeze wins over where the roll is; otherwise custody (facts). */
export function passportBanner(p: Pick<RollPassport, "status" | "custody" | "order" | "lineage">): { tone: Tone; label: string } {
  const atBuyer = `AT BUYER${p.order ? ` (${p.order.buyer})` : ""}`;
  if (p.status === "quarantined" || p.status === "recalled")
    return { tone: "hold", label: p.custody === "at_customer" ? `QUARANTINED · ${atBuyer}` : "QUARANTINED" };
  const onMachine = p.lineage[p.lineage.length - 1]?.run?.stage ?? "weaving";
  const labels: Record<Custody, string> = {
    rejected: "REJECTED",
    passed_in_store: "PASSED · IN STORE",
    wip: onMachine.toUpperCase(),
    awaiting_qc: "AWAITING QC",
    rework: "REWORK",
    at_customer: atBuyer,
    consumed: "CONSUMED",
  };
  return { tone: custodyTone[p.custody], label: labels[p.custody] };
}
