// The ONLY way the frontend talks to the backend. Pages call api.<area>.<action>(...).
// VITE_USE_MOCKS=true (default) serves the real responses in docs/api-mocks, so screens can be built
// before the backend exists. Set it to false once the FastAPI server is running on :8000.

import { ApiError } from "./errors";
import type {
  AttendanceRegister,
  AttendanceRequest,
  AttendanceResponse,
  BuyerOrderStatus,
  DispatchRequest,
  DispatchResponse,
  FindCauseResponse,
  FloorAvailability,
  FloorProgress,
  FloorEvent,
  FloorOutput,
  InspectionRequest,
  InventoryMasters,
  LatestRejections,
  InspectionResponse,
  LoginResponse,
  LowStock,
  LotGraph,
  MachineNow,
  MachineState,
  MassBalance,
  PaymentRequest,
  PaymentResponse,
  Pnl,
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
  WageRun,
  YarnCheck,
  RollLabels,
  RollPassport,
  OwnerAlert,
  InvoiceRow,
  ListQuery,
  Page,
  RollListItem,
  StockRow,
  WorkerRow,
  PermissionsInfo,
  Role,
  UserRow,
  ValidationLogRow,
} from "./types";
import { getSession } from "@/lib/auth";
import { openFloorSocket, type SocketStatus } from "./floorSocket";
import { mock } from "./mocks";

export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS !== "false";

type Method = "GET" | "POST" | "PATCH";

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
    permissions: () => request<PermissionsInfo>("GET", "/api/auth/permissions"),
  },
  validationLog: {
    list: (p: ListQuery) => request<Page<ValidationLogRow>>("GET", `/api/validation-log${qs(p)}`), // validation_log.view
  },
  users: {
    list: (p: ListQuery) => request<Page<UserRow>>("GET", `/api/users${qs(p)}`), // users.manage
    update: (id: number, change: { role?: Role; active?: boolean }) => request<UserRow>("PATCH", `/api/users/${id}`, change),
  },
  floor: {
    machines: () => request<MachineNow[]>("GET", "/api/floor/machines"),
    output: (day?: string) => request<FloorOutput>("GET", `/api/floor/output${qs({ day })}`),
    availability: (from?: string, to?: string) =>
      request<FloorAvailability>("GET", `/api/floor/availability${qs({ from, to })}`),
    progress: (at?: string) => request<FloorProgress>("GET", `/api/floor/progress${qs({ at })}`),
    setState: (machineCode: string, state: MachineState, reason?: string) =>
      request<{ machine_code: string; state: MachineState; started_at: string }>(
        "POST",
        `/api/floor/machines/${encodeURIComponent(machineCode)}/state`,
        { state, reason },
      ),
    // Stays connected (reconnects with backoff after a backend/Vite restart, sleep or Wi-Fi change; stops on 4401).
    // onReconnect: re-fetch the board — events sent while disconnected are not replayed.
    subscribe: (onEvent: (e: FloorEvent) => void, onReconnect?: () => void): (() => void) =>
      openFloorSocket<FloorEvent>({
        url: () => {
          const proto = location.protocol === "https:" ? "wss" : "ws";
          return `${proto}://${location.host}/ws/floor?token=${encodeURIComponent(getSession()?.token ?? "")}`;
        },
        onEvent,
        onReconnect,
      }),
  },
  inventory: {
    masters: () => request<InventoryMasters>("GET", "/api/inventory/masters"), // store@ / owner@
    stock: (asOf?: string) => request<StockSnapshot>("GET", `/api/inventory/stock${qs({ as_of: asOf })}`),
    receive: (req: ReceiptRequest) => request<ReceiptResponse>("POST", "/api/inventory/receipts", req),
    lowStock: () => request<LowStock[]>("GET", "/api/inventory/low-stock"),
  },
  production: {
    startWeaving: (req: StartWeavingRequest) =>
      request<StartWeavingResponse>("POST", "/api/production/weaving-runs", req),
  },
  quality: {
    queue: () => request<QualityQueueItem[]>("GET", "/api/quality/queue"),
    rejections: () => request<Rejection[]>("GET", "/api/quality/rejections"),
    latestRejections: () => request<LatestRejections>("GET", "/api/quality/latest-rejections"),
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
  alerts: {
    // Live only (nothing is replayed). Owner / qc; other roles get "forbidden". Reconnects like the floor socket.
    subscribe: (onAlert: (a: OwnerAlert) => void, onStatus?: (s: SocketStatus) => void): (() => void) =>
      openFloorSocket<OwnerAlert>({
        url: () => {
          const proto = location.protocol === "https:" ? "wss" : "ws";
          return `${proto}://${location.host}/ws/alerts?token=${encodeURIComponent(getSession()?.token ?? "")}`;
        },
        onEvent: onAlert,
        onStatus,
      }),
  },
  // Paged / searched / sorted / filtered lists (the original endpoints are unchanged)
  lists: {
    rolls: (p: ListQuery) => request<Page<RollListItem>>("GET", `/api/rolls${qs(p)}`),
    orders: (p: ListQuery) => request<Page<OrderSummary>>("GET", `/api/orders/list${qs(p)}`),
    stock: (p: ListQuery) => request<Page<StockRow>>("GET", `/api/inventory/stock/list${qs(p)}`),
    qcQueue: (p: ListQuery) => request<Page<QualityQueueItem>>("GET", `/api/quality/queue/list${qs(p)}`),
    rejections: (p: ListQuery) => request<Page<Rejection>>("GET", `/api/quality/rejections/list${qs(p)}`),
    invoices: (p: ListQuery) => request<Page<InvoiceRow>>("GET", `/api/finance/invoices${qs(p)}`), // accounts
    workers: (p: ListQuery) => request<Page<WorkerRow>>("GET", `/api/workforce/workers${qs(p)}`), // floor supervisor
  },
  rolls: {
    passport: (code: string) => request<RollPassport>("GET", `/api/rolls/${encodeURIComponent(code)}/passport`),
    labels: (root?: string) => request<RollLabels>("GET", `/api/rolls/labels${qs({ root })}`),
  },
  recalls: {
    preview: (lotCode: string) =>
      request<RecallResponse>("GET", `/api/recalls/preview${qs({ lot_code: lotCode })}`),
    apply: (lotCode: string, reason: string) =>
      request<RecallResponse>("POST", "/api/recalls", { lot_code: lotCode, reason }),
  },
  orders: {
    list: () => request<OrderSummary[]>("GET", "/api/orders"),
    yarnCheck: (code: string) => request<YarnCheck>("GET", `/api/orders/${encodeURIComponent(code)}/yarn-check`),
    track: (token: string) => request<BuyerOrderStatus>("GET", `/api/track/${encodeURIComponent(token)}`, undefined, false),
    // store@ / owner@. Errors: NOT_FOUND, NOT_QC_PASSED, NOT_IN_ORDER, SHADE_MISMATCH, LOT_QUARANTINED,
    // INSUFFICIENT_STOCK, ALREADY_DISPATCHED, VALIDATION_FAILED (see docs/API_CONTRACT.md)
    dispatch: (req: DispatchRequest) => request<DispatchResponse>("POST", "/api/dispatches", req),
  },
  workforce: {
    register: (day?: string) => request<AttendanceRegister>("GET", `/api/workforce/attendance${qs({ day })}`),
    mark: (req: AttendanceRequest) => request<AttendanceResponse>("POST", "/api/workforce/attendance", req),
    wages: (from?: string, to?: string) => request<WageRun>("GET", `/api/workforce/wages${qs({ from, to })}`),
  },
  finance: {
    massBalance: (from?: string, to?: string) =>
      request<MassBalance>("GET", `/api/finance/mass-balance${qs({ from, to })}`),
    rollCosts: (orderCode: string) =>
      request<RollCost[]>("GET", `/api/finance/roll-costs${qs({ order_code: orderCode })}`),
    pnl: (from?: string, to?: string) => request<Pnl>("GET", `/api/finance/pnl${qs({ from, to })}`),
    recordPayment: (req: PaymentRequest) => request<PaymentResponse>("POST", "/api/finance/payments", req),
  },
};

export type Api = typeof real;

export const api: Api = USE_MOCKS ? mock : real;
