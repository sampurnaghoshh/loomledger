// The ONLY way the frontend talks to the backend. Pages call api.<area>.<action>(...).
// VITE_USE_MOCKS=true (default) serves the real responses in docs/api-mocks, so screens can be built
// before the backend exists. Set it to false once the FastAPI server is running on :8000.

import { ApiError } from "./errors";
import type {
  BuyerOrderStatus,
  FindCauseResponse,
  FloorAvailability,
  FloorEvent,
  FloorOutput,
  InspectionRequest,
  InspectionResponse,
  LoginResponse,
  LotGraph,
  MachineNow,
  MachineState,
  MassBalance,
  OrderSummary,
  QualityQueueItem,
  ReceiptRequest,
  ReceiptResponse,
  RecallResponse,
  Rejection,
  RollCost,
  StartWeavingRequest,
  StartWeavingResponse,
  StockSnapshot,
} from "./types";
import { getSession } from "@/lib/auth";
import { mock } from "./mocks";

export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS !== "false";

type Method = "GET" | "POST";

async function request<T>(method: Method, path: string, body?: unknown, auth = true): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = getSession()?.token;
  if (auth && token) headers.Authorization = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError("NETWORK", "Can't reach the LoomLedger server. Check that the backend is running.");
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw ApiError.fromBody(res.status, data);
  return data as T;
}

const qs = (params: Record<string, string | undefined>) => {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && p.set(k, v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

const real = {
  auth: {
    login: (email: string, password: string) =>
      request<LoginResponse>("POST", "/api/auth/login", { email, password }, false),
  },
  floor: {
    machines: () => request<MachineNow[]>("GET", "/api/floor/machines"),
    output: (day?: string) => request<FloorOutput>("GET", `/api/floor/output${qs({ day })}`),
    availability: (from?: string, to?: string) =>
      request<FloorAvailability>("GET", `/api/floor/availability${qs({ from, to })}`),
    setState: (machineCode: string, state: MachineState, reason?: string) =>
      request<{ machine_code: string; state: MachineState; started_at: string }>(
        "POST",
        `/api/floor/machines/${encodeURIComponent(machineCode)}/state`,
        { state, reason },
      ),
    subscribe: (onEvent: (e: FloorEvent) => void): (() => void) => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const token = encodeURIComponent(getSession()?.token ?? "");
      let ws: WebSocket | null = new WebSocket(`${proto}://${location.host}/ws/floor?token=${token}`);
      ws.onmessage = (m) => {
        try {
          onEvent(JSON.parse(m.data) as FloorEvent);
        } catch {
          /* ignore malformed frames */
        }
      };
      return () => {
        ws?.close();
        ws = null;
      };
    },
  },
  inventory: {
    stock: (asOf?: string) => request<StockSnapshot>("GET", `/api/inventory/stock${qs({ as_of: asOf })}`),
    receive: (req: ReceiptRequest) => request<ReceiptResponse>("POST", "/api/inventory/receipts", req),
  },
  production: {
    startWeaving: (req: StartWeavingRequest) =>
      request<StartWeavingResponse>("POST", "/api/production/weaving-runs", req),
  },
  quality: {
    queue: () => request<QualityQueueItem[]>("GET", "/api/quality/queue"),
    rejections: () => request<Rejection[]>("GET", "/api/quality/rejections"),
    inspect: (req: InspectionRequest) => request<InspectionResponse>("POST", "/api/quality/inspections", req),
  },
  trace: {
    findCause: (lotCodes: string[]) =>
      request<FindCauseResponse>("POST", "/api/trace/find-cause", { lot_codes: lotCodes }),
    ancestors: (lotCodes: string[]) =>
      request<LotGraph & { lot_codes: string[] }>("POST", "/api/trace/graph", { lot_codes: lotCodes, direction: "up" }),
    descendants: (lotCode: string) =>
      request<LotGraph & { lot_code: string }>("GET", `/api/trace/lots/${encodeURIComponent(lotCode)}/descendants`),
  },
  recalls: {
    preview: (lotCode: string) =>
      request<RecallResponse>("GET", `/api/recalls/preview${qs({ lot_code: lotCode })}`),
    apply: (lotCode: string, reason: string) =>
      request<RecallResponse>("POST", "/api/recalls", { lot_code: lotCode, reason }),
  },
  orders: {
    list: () => request<OrderSummary[]>("GET", "/api/orders"),
    track: (token: string) => request<BuyerOrderStatus>("GET", `/api/track/${encodeURIComponent(token)}`, undefined, false),
  },
  finance: {
    massBalance: (from?: string, to?: string) =>
      request<MassBalance>("GET", `/api/finance/mass-balance${qs({ from, to })}`),
    rollCosts: (orderCode: string) =>
      request<RollCost[]>("GET", `/api/finance/roll-costs${qs({ order_code: orderCode })}`),
  },
};

export type Api = typeof real;

export const api: Api = USE_MOCKS ? mock : real;
