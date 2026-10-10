// Mock implementation of the API, backed by REAL responses exported from the seeded database
// (docs/api-mocks/*.json, regenerated with `python -m scripts.export_mocks`).
// It is stateful in one way that matters for rehearsing the demo: after recalls.apply(),
// previews, buyer pages and blocked moves switch to their post-recall versions. Refresh to reset.

import type { Api } from "./client";
import { ApiError } from "./errors";
import type {
  AttendanceRegister,
  BuyerOrderStatus,
  DispatchResponse,
  FindCauseResponse,
  FloorAvailability,
  FloorProgress,
  FloorEvent,
  FloorOutput,
  InventoryMasters,
  LatestRejections,
  LoginResponse,
  LotGraph,
  MachineNow,
  LowStock,
  MassBalance,
  YarnCheck,
  ReceiptResponse,
  PaymentResponse,
  Pnl,
  OrderSummary,
  QualityQueueItem,
  RecallResponse,
  Rejection,
  RollCost,
  Role,
  StockSnapshot,
  WageRun,
  RollLabels,
  RollPassport,
  BreakdownAlert,
  OwnerAlert,
  InvoiceRow,
  ListQuery,
  Page,
  RollListItem,
  StockRow,
  WorkerRow,
} from "./types";

const TOKENS = {
  "4155711b-d0c4-5f02-a2b5-bfd8dd09045d": "SO-0412",
  "8b1ab95b-593a-5796-b23b-a7bdfc0cddd4": "SO-0419",
} as const;

let recallApplied = false;
// Owner alerts in mock mode: whatever /alerts page is open in THIS tab hears recalls.apply() and mock breakdowns.
const alertListeners = new Set<(a: OwnerAlert) => void>();
async function emitAlert(loader: () => Promise<{ default: unknown }>, at: "applied_at" | "started_at", patch: object = {}) {
  const alert = { ...(await load<OwnerAlert>(loader)), [at]: new Date().toISOString(), ...patch } as OwnerAlert;
  alertListeners.forEach((fn) => fn(alert));
}
const YARN_CHECKS: Record<string, () => Promise<{ default: unknown }>> = {
  "SO-0398": () => import("@mocks/orders_yarn_check_SO-0398.json"),
  "SO-0405": () => import("@mocks/orders_yarn_check_SO-0405.json"),
  "SO-0412": () => import("@mocks/orders_yarn_check_SO-0412.json"),
  "SO-0419": () => import("@mocks/orders_yarn_check_SO-0419.json"),
};

// QR passports exported for one roll per banner + the clean roll, before and after the Y-112 recall
type Loader = () => Promise<{ default: unknown }>;
const PASSPORTS: Record<string, { before: Loader; after: Loader }> = {
  "R-1201": { before: () => import("@mocks/roll_passport_R-1201_before.json"), after: () => import("@mocks/roll_passport_R-1201_after.json") },
  "R-1204": { before: () => import("@mocks/roll_passport_R-1204_before.json"), after: () => import("@mocks/roll_passport_R-1204_after.json") },
  "R-1206": { before: () => import("@mocks/roll_passport_R-1206_before.json"), after: () => import("@mocks/roll_passport_R-1206_after.json") },
  "R-1212-G": { before: () => import("@mocks/roll_passport_R-1212-G_before.json"), after: () => import("@mocks/roll_passport_R-1212-G_after.json") },
  "R-1003": { before: () => import("@mocks/roll_passport_R-1003_before.json"), after: () => import("@mocks/roll_passport_R-1003_after.json") },
};

// receipt + dispatch mock state (cleared on refresh, like the recall)
const receiptsByKey = new Map<string, ReceiptResponse>();
const receivedLots = new Set<string>();
const dispatchesByKey = new Map<string, DispatchResponse>();
const shippedRolls = new Set<string>();
const dispatchCount: Record<string, number> = {};

// Paged lists in mock mode: the same query language as app/listing.py, applied in the browser to the mock files.
const PAGING = new Set(["page", "page_size", "q", "sort"]);
const POSITIVE: Record<string, string> = { late: "delay_days", unpaid: "outstanding" };
function mockPage<T extends object>(rows: T[], p: ListQuery, search: (keyof T)[], defaultSort: string): Page<T> {
  const val = (r: T, k: string) => (r as Record<string, unknown>)[k];
  let out = rows.filter((r) =>
    Object.entries(p).every(([k, v]) => {
      if (v === undefined || v === "" || PAGING.has(k)) return true;
      if (POSITIVE[k]) return (Number(val(r, POSITIVE[k]) ?? 0) > 0) === (v === "true");
      return String(val(r, k)) === v;
    }),
  );
  const q = p.q?.trim().toLowerCase();
  if (q) out = out.filter((r) => search.some((k) => String(val(r, k as string) ?? "").toLowerCase().includes(q)));
  const sort = p.sort || defaultSort;
  const key = sort.replace(/^-/, "");
  const dir = sort.startsWith("-") ? -1 : 1;
  out = [...out].sort((a, b) => {
    const x = val(a, key), y = val(b, key);
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
    return (x < y ? -1 : x > y ? 1 : 0) * dir;
  });
  const page = Math.max(1, Number(p.page) || 1);
  const size = Math.min(100, Math.max(1, Number(p.page_size) || 25));
  return { items: out.slice((page - 1) * size, page * size), total: out.length, page, page_size: size };
}

const delay = (ms = 250) => new Promise((r) => setTimeout(r, ms));
async function load<T>(loader: () => Promise<{ default: unknown }>): Promise<T> {
  await delay();
  return structuredClone((await loader()).default) as T;
}

export const mock: Api = {
  auth: {
    login: async (email, password) => {
      await delay();
      const base = await load<LoginResponse>(() => import("@mocks/auth_login.json"));
      const role = email.split("@")[0];
      const roles: Record<string, Role> = {
        owner: "owner",
        store: "store",
        floor: "floor_supervisor",
        qc: "qc",
        accounts: "accounts",
      };
      if (password !== "demo1234" || !roles[role] || !email.endsWith("@everest.test")) {
        throw new ApiError("INVALID_CREDENTIALS", "Email or password is incorrect.", 401);
      }
      return { token: "mock-token", user: { ...base.user, email, role: roles[role] } };
    },
  },
  floor: {
    machines: () => load<MachineNow[]>(() => import("@mocks/floor_machines.json")),
    output: () => load<FloorOutput>(() => import("@mocks/floor_output.json")),
    availability: () => load<FloorAvailability>(() => import("@mocks/floor_availability.json")),
    progress: () => load<FloorProgress>(() => import("@mocks/floor_progress.json")), // the story clock, 09:30
    setState: async (machineCode, state, reason) => {
      await delay();
      if (state === "breakdown")
        void emitAlert(() => import("@mocks/ws_alert_breakdown.json"), "started_at", {
          machine_code: machineCode, machine_name: machineCode.replace(/^LOOM-/, "Loom "), reason: reason ?? null,
        } satisfies Partial<BreakdownAlert>);
      return { machine_code: machineCode, state, started_at: new Date().toISOString() };
    },
    subscribe: (onEvent) => {
      // one realistic event 8 s after subscribing: Loom 4 breaks down
      const t = setTimeout(async () => {
        const e = await load<FloorEvent>(() => import("@mocks/ws_floor_event.json"));
        onEvent({ ...e, started_at: new Date().toISOString() });
      }, 8000);
      return () => clearTimeout(t);
    },
  },
  inventory: {
    masters: () => load<InventoryMasters>(() => import("@mocks/inventory_masters.json")),
    stock: (asOf) =>
      asOf
        ? load<StockSnapshot>(() => import("@mocks/inventory_stock_as_of.json"))
        : load<StockSnapshot>(() => import("@mocks/inventory_stock_now.json")),
    lowStock: () =>
      recallApplied
        ? load<LowStock[]>(() => import("@mocks/inventory_low_stock_after_recall.json"))
        : load<LowStock[]>(() => import("@mocks/inventory_low_stock.json")),
    // Mirrors POST /api/inventory/receipts: validation, unknown supplier/product (masters mock), lot code that
    // already exists (stock mock or received this session), and idempotent replay.
    receive: async (req) => {
      await delay();
      const replay = receiptsByKey.get(req.idempotency_key);
      if (replay) return structuredClone(replay);
      const fields: Record<string, string> = {};
      if (!/^Y-\d{3,}$/.test(req.lot_code)) fields.lot_code = "Use Y- and at least 3 digits";
      if (!(req.kg > 0)) fields.kg = "Input should be greater than 0";
      if (!(req.price_per_kg > 0)) fields.price_per_kg = "Input should be greater than 0";
      if (Object.keys(fields).length) throw new ApiError("VALIDATION_FAILED", "Please correct the highlighted fields.", 422, undefined, fields);

      const masters = await load<InventoryMasters>(() => import("@mocks/inventory_masters.json"));
      if (!masters.suppliers.some((s) => s.code === req.supplier_code))
        throw new ApiError("NOT_FOUND", `Supplier ${req.supplier_code} not found.`, 404, undefined, { supplier_code: "unknown supplier" });
      if (req.product_code && !masters.yarn_products.some((p) => p.code === req.product_code))
        throw new ApiError("NOT_FOUND", "Yarn product not found.", 404, undefined, { product_code: "unknown yarn product" });
      if (req.order_code && !masters.open_orders.some((o) => o.code === req.order_code)) {
        const orders = await load<OrderSummary[]>(() => import("@mocks/orders.json"));
        if (orders.some((o) => o.code === req.order_code))
          throw new ApiError("ORDER_CLOSED", `order ${req.order_code} is dispatched; yarn can only be received for an open order`, 422,
            "Pick an open order, or leave the order empty.", { order_code: "order is not open" }, "LL010");
        throw new ApiError("NOT_FOUND", `Order ${req.order_code} not found.`, 404, undefined, { order_code: "unknown order" });
      }
      const stock = await load<StockSnapshot>(() => import("@mocks/inventory_stock_now.json"));
      if (receivedLots.has(req.lot_code) || stock.rows.some((r) => r.lot_code === req.lot_code))
        throw new ApiError("VALIDATION_FAILED", `Lot ${req.lot_code} already exists.`, 422, undefined, { lot_code: "already exists" }, "23505");

      const result: ReceiptResponse = { receipt_code: `GRN-${req.lot_code}`, lot_code: req.lot_code, kg: req.kg, location: "YARN-STORE",
        order_code: req.order_code ?? null };
      receivedLots.add(req.lot_code);
      receiptsByKey.set(req.idempotency_key, result);
      return structuredClone(result);
    },
  },
  production: {
    startWeaving: async (req) => {
      await delay();
      if (recallApplied && req.yarn_lot_code === "Y-112") {
        const body = await load<unknown>(() => import("@mocks/error_lot_quarantined.json"));
        throw ApiError.fromBody(409, body);
      }
      return { run_code: `WV-${Date.now()}`, lot_code: "R-1301-G", yarn_issued_kg: 15.6 };
    },
  },
  quality: {
    queue: () => load<QualityQueueItem[]>(() => import("@mocks/quality_queue.json")),
    rejections: () => load<Rejection[]>(() => import("@mocks/quality_rejections.json")),
    latestRejections: () => load<LatestRejections>(() => import("@mocks/quality_latest_rejections.json")),
    inspect: async (req) => {
      await delay();
      if (req.result !== "pass" && !req.defect_type) {
        throw new ApiError("VALIDATION_FAILED", "Choose a defect type for a failed roll.", 422, undefined, {
          defect_type: "Required when the roll does not pass",
        });
      }
      return { inspection_id: Math.floor(Math.random() * 10000), lot_code: req.lot_code, result: req.result };
    },
  },
  alerts: {
    subscribe: (onAlert, onStatus) => {
      alertListeners.add(onAlert);
      setTimeout(() => onStatus?.("open"), 300);
      return () => void alertListeners.delete(onAlert);
    },
  },
  lists: {
    rolls: async (p) => {
      const labels = await load<RollLabels>(() =>
        recallApplied ? import("@mocks/roll_labels_after.json") : import("@mocks/roll_labels_before.json"),
      );
      const rows: RollListItem[] = labels.rolls.map((r) => ({
        code: r.code, kind: r.code.endsWith("-G") ? "greige" : "finished", product: r.product, qty_m: r.qty_m,
        status: "active", custody: r.custody, order_code: null, buyer: null, qc_result: null, defect_type: null,
        inspected_at: null, created_at: "",
      }));
      return mockPage(rows, p, ["code", "product"], "code");
    },
    orders: async (p) => mockPage(await load<OrderSummary[]>(() => import("@mocks/orders.json")), p, ["code", "buyer", "product"], "promised_date"),
    stock: async (p) => mockPage((await load<{ rows: StockRow[] }>(() => import("@mocks/inventory_stock_now.json"))).rows, p,
      ["lot_code", "product_code", "location_code"], "location_code"),
    qcQueue: async (p) => mockPage(await load<QualityQueueItem[]>(() => import("@mocks/quality_queue.json")), p, ["lot_code", "order_code"], "lot_code"),
    rejections: async (p) => mockPage(await load<Rejection[]>(() => import("@mocks/quality_rejections.json")), p,
      ["lot_code", "order_code", "inspector"], "-inspected_at"),
    invoices: async (p) => mockPage<InvoiceRow>([], p, ["code"], "-issued_at"), // no invoice list in the mock files
    workers: async (p) => {
      const reg = await load<{ workers: { worker_code: string; full_name: string; skill: string | null }[] }>(
        () => import("@mocks/workforce_attendance.json"));
      const rows: WorkerRow[] = reg.workers.map((w) => ({ code: w.worker_code, full_name: w.full_name, skill: w.skill, hourly_wage: 0, active: true }));
      return mockPage(rows, p, ["code", "full_name"], "code");
    },
  },
  rolls: {
    passport: async (code) => {
      if (!/^R-\d{3,}(-G)?$/.test(code)) {
        throw new ApiError("VALIDATION_FAILED", "Please correct the highlighted fields.", 422, undefined, { code: "invalid roll code" });
      }
      const files = PASSPORTS[code];
      if (!files) {
        await delay();
        throw new ApiError("NOT_FOUND", `Unknown roll: ${code}.`, 404, `Mock data has ${Object.keys(PASSPORTS).join(", ")}.`, { code: `unknown: ${code}` });
      }
      return load<RollPassport>(recallApplied ? files.after : files.before);
    },
    labels: () =>
      recallApplied
        ? load<RollLabels>(() => import("@mocks/roll_labels_after.json"))
        : load<RollLabels>(() => import("@mocks/roll_labels_before.json")),
  },
  trace: {
    findCause: () => load<FindCauseResponse>(() => import("@mocks/trace_find_cause.json")),
    ancestors: () => load<LotGraph & { lot_codes: string[] }>(() => import("@mocks/trace_graph_ancestors.json")),
    descendants: () => load<LotGraph & { lot_code: string }>(() => import("@mocks/trace_graph_descendants.json")),
  },
  recalls: {
    preview: () =>
      recallApplied
        ? load<RecallResponse>(() => import("@mocks/recall_applied.json"))
        : load<RecallResponse>(() => import("@mocks/recall_preview.json")),
    apply: async () => {
      if (!recallApplied) void emitAlert(() => import("@mocks/ws_alert_recall.json"), "applied_at"); // once, like COMMIT
      recallApplied = true;
      return load<RecallResponse>(() => import("@mocks/recall_applied.json"));
    },
  },
  orders: {
    list: () => load<OrderSummary[]>(() => import("@mocks/orders.json")),
    // Exported after the recall, like orders.json.
    yarnCheck: async (code) => {
      const loader = YARN_CHECKS[code];
      if (!loader) {
        await delay();
        throw new ApiError("NOT_FOUND", `Order ${code} not found.`, 404, undefined, { order_code: "not found" });
      }
      return load<YarnCheck>(loader);
    },
    track: async (token) => {
      const order = TOKENS[token as keyof typeof TOKENS];
      if (!order) {
        await delay();
        throw new ApiError("NOT_FOUND", "This tracking link is invalid or has expired.", 404);
      }
      if (order === "SO-0412") {
        return recallApplied
          ? load<BuyerOrderStatus>(() => import("@mocks/track_SO-0412_after.json"))
          : load<BuyerOrderStatus>(() => import("@mocks/track_SO-0412_before.json"));
      }
      return recallApplied
        ? load<BuyerOrderStatus>(() => import("@mocks/track_SO-0419_after.json"))
        : load<BuyerOrderStatus>(() => import("@mocks/track_SO-0419_before.json"));
    },
    // Built only from the mock files: amount = roll metres (stock mock) x the order's unit price (orders mock).
    // Not simulated (the mocks carry no dye batch / QC data for store rolls): SHADE_MISMATCH, NOT_QC_PASSED, NOT_IN_ORDER.
    dispatch: async (req) => {
      await delay();
      const replay = dispatchesByKey.get(req.idempotency_key);
      if (replay) return structuredClone(replay);

      const fields: Record<string, string> = {};
      if (!req.lot_codes.length) fields.lot_codes = "Pick at least one roll";
      else if (new Set(req.lot_codes).size !== req.lot_codes.length) fields.lot_codes = "A roll can only be listed once";
      if (!req.vehicle_no.trim()) fields.vehicle_no = "Required";
      if (req.shade_override_reason !== undefined && req.shade_override_reason.trim().length < 3)
        fields.shade_override_reason = "At least 3 characters";
      if (Object.keys(fields).length) throw new ApiError("VALIDATION_FAILED", "Please correct the highlighted fields.", 422, undefined, fields);

      const orders = await load<OrderSummary[]>(() => import("@mocks/orders.json"));
      const order = orders.find((o) => o.code === req.order_code);
      if (!order) throw new ApiError("NOT_FOUND", `Order ${req.order_code} not found.`, 404, undefined, { order_code: "not found" });

      if (recallApplied) {
        const recall = await load<RecallResponse>(() => import("@mocks/recall_applied.json"));
        const held = req.lot_codes.find((c) => recall.rolls.some((r) => r.lot_code === c));
        if (held) {
          const blocked = await load<{ error: { hint: string } }>(() => import("@mocks/error_lot_quarantined.json"));
          throw new ApiError("LOT_QUARANTINED", `stock movement blocked: lot ${held} is quarantined`, 409, blocked.error.hint, undefined, "LL001");
        }
      }
      const again = req.lot_codes.find((c) => shippedRolls.has(c));
      if (again) throw new ApiError("ALREADY_DISPATCHED", "One or more rolls have already been dispatched.", 409, undefined, undefined, "23505");

      const stock = await load<StockSnapshot>(() => import("@mocks/inventory_stock_now.json"));
      const inStore = new Map(stock.rows.filter((r) => r.location_code === "FG-STORE").map((r) => [r.lot_code, r.qty]));
      const missing = req.lot_codes.filter((c) => !inStore.has(c));
      if (missing.length)
        throw new ApiError("NOT_FOUND", `Unknown roll(s): ${missing.join(", ")}.`, 404, undefined, { lot_codes: `unknown: ${missing.join(", ")}` });

      const n = (dispatchCount[order.code] ??= order.progress.dispatched_m > 0 ? 1 : 0) + 1;
      dispatchCount[order.code] = n;
      const digits = order.code.replace(/^SO-/, "");
      const metres = req.lot_codes.reduce((sum, c) => sum + (inStore.get(c) ?? 0), 0);
      const result: DispatchResponse = {
        dispatch_code: `DSP-${digits}-${n}`,
        invoice_code: `INV-${digits}-${n}`,
        amount: metres * order.unit_price,
      };
      req.lot_codes.forEach((c) => shippedRolls.add(c));
      dispatchesByKey.set(req.idempotency_key, result);
      return structuredClone(result);
    },
  },
  workforce: {
    register: () => load<AttendanceRegister>(() => import("@mocks/workforce_attendance.json")),
    mark: async (req) => {
      await delay();
      const fields: Record<string, string> = {};
      if (!req.marks.length) fields.marks = "Mark at least one worker";
      if (new Set(req.marks.map((m) => m.worker_code)).size !== req.marks.length) fields.marks = "A worker can only be marked once";
      if (Object.keys(fields).length) throw new ApiError("VALIDATION_FAILED", "Please correct the highlighted fields.", 422, undefined, fields);
      return { batch_id: 1, day: req.day, shift_code: req.shift_code, marked: req.marks.length, marked_at: new Date().toISOString() };
    },
    wages: () => load<WageRun>(() => import("@mocks/workforce_wages.json")),
  },
  finance: {
    massBalance: () => load<MassBalance>(() => import("@mocks/finance_mass_balance.json")),
    rollCosts: () => load<RollCost[]>(() => import("@mocks/finance_roll_costs_SO-0412.json")),
    pnl: () =>
      recallApplied
        ? load<Pnl>(() => import("@mocks/finance_pnl_after_recall.json"))
        : load<Pnl>(() => import("@mocks/finance_pnl.json")),
    recordPayment: async (req) => {
      await delay();
      if (!(req.amount > 0)) throw new ApiError("VALIDATION_FAILED", "Please correct the highlighted fields.", 422, undefined, { amount: "must be greater than 0" });
      // The one open invoice in the seed is SO-0412's; its balance is Meridian's receivable in finance_pnl.json.
      const pnl = await load<Pnl>(() => import("@mocks/finance_pnl.json"));
      const left = req.invoice_code === "INV-0412-1" ? (pnl.receivables.find((r) => r.buyer_code === "BUY-MER")?.outstanding ?? 0) : 0;
      if (!/^INV-0(398|412)-1$/.test(req.invoice_code))
        throw new ApiError("NOT_FOUND", `Invoice ${req.invoice_code} not found.`, 404, undefined, { invoice_code: "not found" });
      if (req.amount > left)
        throw new ApiError("OVERPAYMENT", `payment of ${req.amount} exceeds the ${left} outstanding on ${req.invoice_code}`, 422,
          "Record at most the outstanding amount.", { amount: `at most ${left}` }, "LL009");
      const res: PaymentResponse = { payment_id: 3, invoice_code: req.invoice_code, amount: req.amount, method: req.method,
        paid_at: new Date().toISOString(), invoice_amount: left, outstanding_after: left - req.amount };
      return res;
    },
  },
};
