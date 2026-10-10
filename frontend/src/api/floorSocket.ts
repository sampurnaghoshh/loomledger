// A WebSocket that stays connected: the live floor board must survive a backend restart, a Vite restart,
// a laptop waking up or a Wi-Fi change without anyone pressing F5.
// Self-contained (no "@/" imports) so `node --test` can run tests/floorSocket.test.ts directly.

export const UNAUTHORIZED_CLOSE = 4401; // the server's "bad or expired token": reconnecting can't help
export const BACKOFF_MS = [1000, 2000, 5000, 10000, 15000];

export interface SocketLike {
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code: number }) => void) | null;
  close(): void;
}

export interface FloorSocketOptions<E> {
  /** Built again for every attempt, so a renewed session token is picked up. */
  url: () => string;
  onEvent: (event: E) => void;
  /** Called after a REconnect: events may have been missed while disconnected, so re-fetch the current state. */
  onReconnect?: () => void;
  createSocket?: (url: string) => SocketLike;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (timer: unknown) => void;
  backoffMs?: number[];
}

/** Opens the socket and keeps it open. Returns the unsubscribe function. */
export function openFloorSocket<E>(opts: FloorSocketOptions<E>): () => void {
  const create = opts.createSocket ?? ((url: string) => new WebSocket(url) as unknown as SocketLike);
  const setTimer = opts.setTimer ?? ((fn: () => void, ms: number) => setTimeout(fn, ms));
  const clearTimer = opts.clearTimer ?? ((t: unknown) => clearTimeout(t as ReturnType<typeof setTimeout>));
  const backoff = opts.backoffMs ?? BACKOFF_MS;

  let socket: SocketLike | null = null;
  let timer: unknown = null;
  let stopped = false;
  let failures = 0; // consecutive closes since the last successful open
  let lostConnection = false; // true once a socket that was (or should have been) open went away

  const connect = () => {
    if (stopped) return;
    const ws = create(opts.url());
    socket = ws;
    ws.onopen = () => {
      failures = 0;
      if (lostConnection) {
        lostConnection = false;
        opts.onReconnect?.();
      }
    };
    ws.onmessage = (m) => {
      try {
        opts.onEvent(JSON.parse(String(m.data)) as E);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = (ev) => {
      if (socket === ws) socket = null;
      if (stopped || ev.code === UNAUTHORIZED_CLOSE) return;
      lostConnection = true;
      const delay = backoff[Math.min(failures, backoff.length - 1)];
      failures += 1;
      timer = setTimer(connect, delay);
    };
  };

  connect();
  return () => {
    stopped = true;
    if (timer !== null) clearTimer(timer);
    socket?.close();
    socket = null;
  };
}
