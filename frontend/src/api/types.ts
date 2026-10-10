// Response shapes of the LoomLedger API. They mirror docs/api-mocks/*.json exactly.
// Numbers are plain JSON numbers; dates are ISO strings ("2026-10-16"); timestamps are ISO with +05:30.

export type Role = "owner" | "store" | "floor_supervisor" | "qc" | "accounts";
export type MachineStage = "spinning" | "weaving" | "dyeing" | "finishing";
export type MachineState = "running" | "idle" | "breakdown" | "changeover";
export type LotKind = "yarn" | "greige" | "finished";
export type LotStatus = "active" | "wip" | "consumed" | "dispatched" | "quarantined" | "recalled";
export type Custody =
  | "consumed"
  | "at_customer"
  | "wip"
  | "rejected"
  | "rework"
  | "passed_in_store"
  | "awaiting_qc";
export type QcResult = "pass" | "rework" | "reject";
export type Verdict = "root_cause" | "coincidental" | "partial" | "no_comparison";

// ---------- auth
export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
}
export interface LoginResponse {
  token: string;
  user: User;
}

// ---------- floor
export interface MachineNow {
  code: string;
  name: string;
  stage: MachineStage;
  state: MachineState;
  state_since: string | null;
  reason: string | null;
  current_run: string | null;
  current_lot: string | null;
  current_order: string | null;
}
export interface FloorOutput {
  day: string;
  machines: { machine_code: string; machine_name: string; stage: MachineStage; runs_completed: number; meters: number }[];
}
export interface FloorAvailability {
  from: string;
  to: string;
  machines: { machine_code: string; running_h: number; breakdown_h: number; availability_pct: number | null }[];
}
export interface FloorEvent {
  machine_id: number;
  machine_code: string;
  state: MachineState;
  reason: string | null;
  started_at: string;
  ended_at: string | null;
}

// ---------- inventory
export interface StockRow {
  location_code: string;
  lot_code: string;
  lot_kind: LotKind;
  product_code: string;
  qty: number;
  uom: "kg" | "m";
}
export interface InventoryMasters {
  suppliers: { code: string; name: string }[];
  yarn_products: { code: string; name: string }[];
}
export interface StockSnapshot {
  as_of: string | null; // null = now
  rows: StockRow[];
}

// ---------- quality
export interface QualityQueueItem {
  lot_code: string;
  product: string;
  qty_m: number;
  dye_batch: string;
  dyed_on: string;
  dyed_at: string;
  order_code: string | null;
}
export interface LatestRejections {
  day: string | null; // mill-time date of the most recent rejection ("latest", not the viewer's today)
  rejections: Rejection[]; // that day's rejections, newest first
}
export interface Rejection {
  lot_code: string;
  defect_type: string;
  defect_meters: number | null;
  inspected_at: string;
  inspector: string;
  order_code: string | null;
}

// ---------- trace
export interface CauseFactor {
  factor_kind: "yarn_lot" | "machine" | "shift";
  factor_label: string;
  selected_covered: number;
  selected_total: number;
  inspected_through: number;
  rejected_through: number;
  rate_through_pct: number | null;
  inspected_outside: number;
  rejected_outside: number;
  rate_outside_pct: number | null;
  lift: number | null;
  verdict: Verdict;
}
export interface FindCauseResponse {
  selected: string[];
  factors: CauseFactor[]; // already ranked: factors[0] is the strongest candidate
}
export interface GraphNode {
  code: string;
  kind: LotKind;
  product: string;
  qty: number;
  uom: "kg" | "m";
  status: LotStatus;
  custody: Custody | null; // null for yarn
  machine: string | null;
  stage: MachineStage | null;
  shift: string | null;
  run_code: string | null;
  produced_at: string;
  supplier: string | null;
}
export interface GraphEdge {
  from: string;
  to: string;
  qty_consumed: number;
}
export interface LotGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ---------- recall
export interface RecallImpact {
  root_lot_code: string;
  rolls_total: number;
  rolls_rejected: number;
  rolls_at_risk: number;
  rolls_passed_in_store: number;
  rolls_awaiting_qc: number;
  rolls_wip: number;
  rolls_at_customer: number;
  orders_affected: number;
  buyers_affected: number;
  buyers_holding_goods: number;
  remake_m: number;
  bottleneck_stage: MachineStage | null;
  throughput_m_per_day: number | null;
  additional_delay_days: number;
  cost_already_incurred: number;
  cost_in_factory: number;
  cost_wip: number;
  cost_at_customer: number;
  recall_exposure: number;
  quarantined_material_qty: number;
  quarantined_material_value: number;
  total_exposure: number;
}
export interface RecallOrderImpact {
  order_id: number;
  order_code: string;
  buyer_name: string;
  product_code: string;
  affected_rolls: number;
  rolls_at_customer: number;
  at_customer_codes: string | null;
  remake_m: number;
  bottleneck_stage: MachineStage;
  throughput_m_per_day: number;
  cumulative_remake_m: number;
  delay_days: number;
  promised_date: string;
  revised_promise_date: string;
}
export interface RecallRoll {
  lot_code: string;
  kind: LotKind;
  qty_m: number;
  custody: Custody;
  order_code: string | null;
  buyer_name: string | null;
  cost: number;
}
export interface RecallResponse {
  applied: boolean;
  recall_code: string | null;
  applied_at?: string;
  lot_code: string;
  impact: RecallImpact;
  orders: RecallOrderImpact[];
  rolls: RecallRoll[];
  calculation: {
    formula: string;
    remake_m: number;
    throughput_m_per_day: number;
    raw_days: number;
    additional_delay_days: number;
    display: string; // "600 ÷ 250 = 2.4 → ceil = 3 working days"
  };
}

// ---------- orders & buyer portal
export interface OrderProgress {
  ready_m: number;
  on_hold_m: number;
  weaving_m: number;
  dispatched_m: number;
  quality_check_m: number;
}
export interface OrderSummary {
  code: string;
  buyer: string;
  product: string;
  ordered_m: number;
  unit_price: number;
  promised_date: string;
  revised_promise_date: string | null;
  delay_days: number; // working days (Mon–Sat) from promised to revised; 0 when on time
  status: "confirmed" | "in_production" | "partially_dispatched" | "dispatched" | "cancelled";
  progress: OrderProgress;
  tracking_token: string; // buyer page: /track/<tracking_token>
}
export interface BuyerOrderStatus {
  order: string;
  buyer: string;
  product: string;
  ordered_m: number;
  promised_date: string;
  expected_date: string;
  delayed: boolean;
  progress: OrderProgress;
  updates: { at: string; message: string }[]; // newest first
}

// ---------- workforce
export type AttendanceStatus = "present" | "absent" | "half_day" | "leave";
export interface AttendanceRegister {
  day: string;
  shifts: { code: string; name: string; starts_at: string; ends_at: string }[];
  workers: { worker_code: string; full_name: string; skill: MachineStage | null; status: AttendanceStatus | null; shift_code: string | null }[];
}
export interface AttendanceRequest {
  day: string;
  shift_code: string;
  marks: { worker_code: string; status: AttendanceStatus }[];
  idempotency_key: string;
}
export interface AttendanceResponse {
  batch_id: number;
  day: string;
  shift_code: string;
  marked: number;
  marked_at: string;
}
export interface WageRow {
  worker_code: string;
  full_name: string;
  skill: MachineStage | null;
  hourly_wage: number;
  days_worked: number;
  shifts_worked: number;
  half_days: number;
  absent_days: number;
  leave_days: number;
  gross_wage: number;
}
export interface WageRun {
  from: string;
  to: string;
  totals: { workers: number; days_worked: number; shifts_worked: number; gross_wage: number };
  workers: WageRow[];
}

// ---------- finance
export interface MassBalance {
  from: string | null; // null = to date (all runs so far)
  to: string | null;
  first_run_at: string | null; // earliest weaving run in the window ("to date, since …"); null if none
  totals: {
    received_kg: number;
    issued_kg: number;
    fabric_kg: number;
    waste_kg: number;
    wip_kg: number;
    unaccounted_kg: number;
    unaccounted_pct: number;
  };
  by_machine: {
    machine_code: string;
    machine_name: string;
    runs: number;
    issued_kg: number;
    unaccounted_kg: number;
    unaccounted_pct: number;
  }[];
}
export interface RollCost {
  lot_code: string;
  qty_m: number;
  material: number;
  machine: number;
  labour: number;
  chemicals: number;
  total: number;
  cost_per_m: number;
  custody: Custody;
  status: LotStatus;
}

// ---------- write requests (see docs/API_CONTRACT.md)
export interface ReceiptRequest {
  supplier_code: string;
  lot_code: string;
  kg: number;
  price_per_kg: number;
  vehicle_no?: string;
  challan_no?: string;
  product_code?: string; // yarn product (api.inventory.masters); omitted = the only yarn product
  idempotency_key: string;
}
export interface ReceiptResponse {
  receipt_code: string;
  lot_code: string;
  kg: number;
  location: string;
}
export interface InspectionRequest {
  lot_code: string;
  result: QcResult;
  defect_type?: string;
  defect_meters?: number;
  notes?: string;
  inspector_code?: string; // omitted = the first active QC inspector
  idempotency_key?: string; // send newIdempotencyKey(): a replayed reject returns the original
}
export interface InspectionResponse {
  inspection_id: number;
  lot_code: string;
  result: QcResult;
}
export interface StartWeavingRequest {
  machine_code: string;
  yarn_lot_code: string;
  product_code: string;
  meters_planned: number;
  order_code?: string;
  operator_code?: string; // omitted = the first free weaver
  idempotency_key: string;
}
export interface StartWeavingResponse {
  run_code: string;
  lot_code: string;
  yarn_issued_kg: number;
}
export interface DispatchRequest {
  order_code: string;
  lot_codes: string[]; // finished rolls reserved for this order that passed QC; one dye batch per dispatch
  vehicle_no: string;
  idempotency_key: string; // newIdempotencyKey() once per form: a resend returns the original dispatch
  shade_override_reason?: string; // 3-500 chars; allows mixing dye batches (else 409 SHADE_MISMATCH, fields.batches)
}
export interface DispatchResponse {
  dispatch_code: string;
  invoice_code: string;
  amount: number; // ₹, Σ roll metres × order line price
}
