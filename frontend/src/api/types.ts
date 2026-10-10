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
/** GET /api/floor/progress — estimated progress of every open run (no metre counter: running time vs planned time). */
export interface RunProgress {
  machine_code: string;
  machine_name: string;
  state: MachineState; // at `at`
  run_code: string;
  lot_code: string;
  order_code: string | null;
  started_at: string;
  planned_m: number;
  rated_m_per_hour: number;
  planned_hours: number;
  productive_hours: number; // time running since the run started
  paused_hours: number; // breakdowns / changeovers since the run started
  progress_pct: number; // capped at 100
  est_done_m: number;
  remaining_hours: number;
  over_plan_hours: number;
  expected_end: string | null; // null while the machine is stopped
  woven_to_plan_at: string | null; // due off the loom since; null while under plan
}
export interface FloorProgress {
  at: string;
  runs: RunProgress[];
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
  order_code: string | null; // yarn received at the gate for this order (null = general stock)
}
export interface InventoryMasters {
  suppliers: { code: string; name: string }[];
  yarn_products: { code: string; name: string }[];
  open_orders: { code: string; buyer: string }[]; // what a receipt can be for (dispatched/cancelled are refused)
}
/** GET /api/inventory/low-stock — yarn whose free stock is below its reorder level (migration 014). */
export interface LowStock {
  product_code: string;
  product_name: string;
  on_hand_kg: number; // usable: in the yarn store, not quarantined
  quarantined_kg: number; // held — never counted as available
  committed_kg: number; // what the open orders still need to weave
  open_orders: number;
  available_kg: number; // on hand − committed; negative = the order book needs more yarn than we have
  reorder_level_kg: number;
  below_reorder_kg: number;
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
  yarn_status: "ok" | "short" | null; // null = closed order
  yarn_required_kg: number | null;
  yarn_shortfall_kg: number | null;
  yarn_short_of: string | null; // yarn product name(s) it is short of
  to_weave_m: number | null; // metres still to weave, remakes included; null = closed order
}
/** GET /api/orders/{code}/yarn-check — enough yarn to weave what the order still needs? */
export interface YarnCheck {
  order_code: string;
  status: "ok" | "short" | "closed";
  due: string; // revised promise date if any
  required_kg: number;
  shortfall_kg: number;
  orders_ahead: string[]; // open orders that take the same yarn first
  lines: {
    product_code: string;
    product: string;
    yarn_product_code: string;
    yarn_product: string;
    ordered_m: number;
    covered_m: number; // reserved rolls that are not rejected, quarantined or recalled
    unwoven_m: number;
    required_kg: number;
    available_kg: number; // usable yarn left for this order after the orders due before it
    shortfall_kg: number;
  }[];
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
/** GET /api/finance/pnl — the month's books, two honest views (migration 013 monthly_pnl). */
export interface Pnl {
  from: string;
  to: string;
  /** Profit, accrual basis: revenue - cost of the invoiced rolls (without labour) - the period's wages. */
  accrual: {
    invoices: number;
    rolls_invoiced: number;
    revenue: number;
    material: number;
    machine: number;
    chemicals: number;
    cost_of_goods_sold: number;
    /** lot_cost's labour for the invoiced rolls — left out of COGS because wages already pay it. */
    labour_in_lot_cost_excluded: number;
    wages: number;
    profit: number;
  };
  /** Cash: buyer payments received - yarn bills paid - wages. */
  cash: {
    received_from_buyers: number;
    yarn_bills_paid: number;
    wages_paid: number;
    wages_paid_basis: string;
    net_cash: number;
  };
  receivables: { buyer_code: string; buyer: string; invoices: number; outstanding: number }[];
  receivables_total: number;
  payables: { supplier_code: string; supplier: string; bills: number; outstanding: number }[];
  payables_total: number;
  /** Recalls applied in the period — contingent exposure, not subtracted from profit. */
  recalls: {
    recall_code: string;
    lot_code: string;
    applied_at: string;
    total_exposure: number;
    cost_already_incurred: number;
    recall_exposure: number;
    quarantined_material_value: number;
  }[];
}
export type PaymentMethod = "bank_transfer" | "cheque" | "upi" | "cash";
export interface PaymentResponse {
  payment_id: number;
  invoice_code: string;
  amount: number;
  method: PaymentMethod;
  paid_at: string;
  invoice_amount: number;
  outstanding_after: number;
}

// ---------- write requests (see docs/API_CONTRACT.md)
export interface PaymentRequest {
  invoice_code: string;
  amount: number;
  method: PaymentMethod;
  idempotency_key: string;
}
export interface ReceiptRequest {
  supplier_code: string;
  lot_code: string;
  kg: number;
  price_per_kg: number;
  vehicle_no?: string;
  challan_no?: string;
  product_code?: string; // yarn product (api.inventory.masters); omitted = the only yarn product
  order_code?: string; // which open order the yarn is for (optional)
  idempotency_key: string;
}
export interface ReceiptResponse {
  receipt_code: string;
  lot_code: string;
  kg: number;
  location: string;
  order_code: string | null;
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

/** GET /api/rolls/{code}/passport — everything a roll's QR code answers (F1). */
export interface RollPassportStep {
  lot_code: string;
  kind: LotKind;
  product: string;
  qty: number;
  uom: "kg" | "m";
  depth: number; // 0 = this roll, 1 = its parent, ...
  receipt: { code: string; supplier: string; received_at: string } | null; // yarn: bought
  run: {
    code: string;
    stage: MachineStage;
    machine: string;
    shift: string;
    operator: string;
    started_at: string;
    ended_at: string | null; // null = still on the machine
  } | null; // fabric: made
}
export interface RollPassport {
  code: string;
  kind: "greige" | "finished";
  status: LotStatus; // quarantined / recalled once a recall froze it
  custody: Custody; // where it is, derived from facts
  qty_m: number;
  product_code: string;
  product: string;
  colour: string | null;
  lineage: RollPassportStep[]; // oldest first; the roll itself last
  qc: { result: QcResult; defect_type: string | null; defect_m: number | null; inspector: string; inspected_at: string } | null;
  cost: { material: number; machine: number; labour: number; chemicals: number; total: number; cost_per_m: number };
  order: { code: string; buyer: string; status: string; promised_date: string; revised_promise_date: string | null } | null;
  dispatch: { code: string; dispatched_at: string; vehicle_no: string | null; invoice_code: string | null } | null;
  recall: { code: string; root_lot_code: string; reason: string; initiated_at: string } | null;
}
/** GET /api/rolls/labels — rolls to print QR labels for: a family (in_scope) + one clean roll. */
export interface RollLabel {
  code: string;
  product: string;
  qty_m: number;
  custody: Custody;
  in_scope: boolean;
}
export interface RollLabels {
  root: string | null;
  rolls: RollLabel[];
}

/** WS /ws/alerts — live owner alerts (016). Sent by PostgreSQL: a recall at COMMIT, or a machine breakdown. */
export interface RecallAlert {
  kind: "recall";
  recall_code: string;
  root_lot_code: string;
  reason: string;
  applied_at: string;
  rolls_total: number;
  rolls_rejected: number;
  rolls_at_risk: number;
  rolls_at_customer: number;
  at_buyers: { buyer: string; rolls: string[] }[];
  orders_affected: number;
  buyers_affected: number;
  delay_days: number; // the worst order's extra working days
  orders: { order_code: string; buyer: string; delay_days: number; promised_date: string; revised_promise_date: string }[];
  total_exposure: number;
}
export interface BreakdownAlert {
  kind: "breakdown";
  machine_code: string;
  machine_name: string;
  reason: string | null;
  started_at: string;
}
export type OwnerAlert = RecallAlert | BreakdownAlert;

/** Paged lists (app/listing.py): ?page=&page_size=&q=&sort=(-)col&<filters> -> one page + the total. */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number; // what was used (capped at 100)
}
/** The list query exactly as it sits in the URL: page, page_size, q, sort and the endpoint's filters. */
export type ListQuery = Record<string, string | undefined>;
export interface RollListItem {
  code: string;
  kind: "greige" | "finished";
  product: string;
  qty_m: number;
  status: LotStatus;
  custody: Custody;
  order_code: string | null;
  buyer: string | null;
  qc_result: QcResult | null;
  defect_type: string | null;
  inspected_at: string | null;
  created_at: string;
}
export interface InvoiceRow {
  code: string;
  order_code: string;
  buyer: string;
  dispatch_code: string;
  dispatched_at: string;
  rolls: number;
  amount: number;
  paid: number;
  outstanding: number;
  issued_at: string;
}
export interface WorkerRow {
  code: string;
  full_name: string;
  skill: string | null;
  hourly_wage: number;
  active: boolean;
}
