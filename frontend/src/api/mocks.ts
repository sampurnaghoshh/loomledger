// Mock implementation of the API, backed by REAL responses exported from the seeded database
// (docs/api-mocks/*.json, regenerated with `python -m scripts.export_mocks`).
// It is stateful in one way that matters for rehearsing the demo: after recalls.apply(),
// previews, buyer pages and blocked moves switch to their post-recall versions. Refresh to reset.

import type { Api } from "./client";
import { ApiError } from "./errors";
import type {
  BuyerOrderStatus,
  DispatchResponse,
  FindCauseResponse,
  FloorAvailability,
  FloorEvent,
  FloorOutput,
  InventoryMasters,
  LatestRejections,
  LoginResponse,
  LotGraph,
  MachineNow,
  MassBalance,
  OrderSummary,
  QualityQueueItem,
  RecallResponse,
  Rejection,
  RollCost,
  Role,
  StockSnapshot,
} from "./types";

const TOKENS = {
  "4155711b-d0c4-5f02-a2b5-bfd8dd09045d": "SO-0412",
  "8b1ab95b-593a-5796-b23b-a7bdfc0cddd4": "SO-0419",
} as const;

let recallApplied = false;

// receipt + dispatch mock state (cleared on refresh, like the recall)
const receiptsByKey = new Map<string, { receipt_code: string; lot_code: string; kg: number; location: string }>();
const receivedLots = new Set<string>();
const dispatchesByKey = new Map<string, DispatchResponse>();
const shippedRolls = new Set<string>();
const dispatchCount: Record<string, number> = {};

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
    setState: async (machineCode, state) => {
      await delay();
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
      const stock = await load<StockSnapshot>(() => import("@mocks/inventory_stock_now.json"));
      if (receivedLots.has(req.lot_code) || stock.rows.some((r) => r.lot_code === req.lot_code))
        throw new ApiError("VALIDATION_FAILED", `Lot ${req.lot_code} already exists.`, 422, undefined, { lot_code: "already exists" }, "23505");

      const result = { receipt_code: `GRN-${req.lot_code}`, lot_code: req.lot_code, kg: req.kg, location: "YARN-STORE" };
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
      recallApplied = true;
      return load<RecallResponse>(() => import("@mocks/recall_applied.json"));
    },
  },
  orders: {
    list: () => load<OrderSummary[]>(() => import("@mocks/orders.json")),
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
  finance: {
    massBalance: () => load<MassBalance>(() => import("@mocks/finance_mass_balance.json")),
    rollCosts: () => load<RollCost[]>(() => import("@mocks/finance_roll_costs_SO-0412.json")),
  },
};
