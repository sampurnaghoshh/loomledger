// Mock implementation of the API, backed by REAL responses exported from the seeded database
// (docs/api-mocks/*.json, regenerated with `python -m scripts.export_mocks`).
// It is stateful in one way that matters for rehearsing the demo: after recalls.apply(),
// previews, buyer pages and blocked moves switch to their post-recall versions. Refresh to reset.

import type { Api } from "./client";
import { ApiError } from "./errors";
import type {
  BuyerOrderStatus,
  FindCauseResponse,
  FloorAvailability,
  FloorEvent,
  FloorOutput,
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
    stock: (asOf) =>
      asOf
        ? load<StockSnapshot>(() => import("@mocks/inventory_stock_as_of.json"))
        : load<StockSnapshot>(() => import("@mocks/inventory_stock_now.json")),
    receive: async (req) => {
      await delay();
      if (!req.lot_code.trim()) throw new ApiError("VALIDATION_FAILED", "Lot code is required.", 422, undefined, { lot_code: "Required" });
      return { receipt_code: `GRN-${req.lot_code}`, lot_code: req.lot_code, kg: req.kg, location: "YARN-STORE" };
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
  },
  finance: {
    massBalance: () => load<MassBalance>(() => import("@mocks/finance_mass_balance.json")),
    rollCosts: () => load<RollCost[]>(() => import("@mocks/finance_roll_costs_SO-0412.json")),
  },
};
