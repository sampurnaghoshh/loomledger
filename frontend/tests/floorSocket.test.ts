// node --test tests/   (Node's built-in runner; no test dependency)
import { test } from "node:test";
import assert from "node:assert/strict";
import { BACKOFF_MS, FORBIDDEN_CLOSE, openFloorSocket, UNAUTHORIZED_CLOSE, type SocketLike, type SocketStatus } from "../src/api/floorSocket.ts";

class FakeSocket implements SocketLike {
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  closedByClient = false;
  url: string;
  constructor(url: string) {
    this.url = url;
  }
  close() {
    this.closedByClient = true;
    this.onclose?.({ code: 1000 });
  }
  open() { this.onopen?.({}); }
  send(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }); }
  drop(code = 1006) { this.onclose?.({ code }); }
}

function harness(token = "t1") {
  const sockets: FakeSocket[] = [];
  const timers: { fn: () => void; ms: number }[] = [];
  const events: unknown[] = [];
  let reconnects = 0;
  let currentToken = token;
  const stop = openFloorSocket({
    url: () => `ws://host/ws/floor?token=${currentToken}`,
    onEvent: (e) => events.push(e),
    onReconnect: () => { reconnects += 1; },
    createSocket: (url) => { const s = new FakeSocket(url); sockets.push(s); return s; },
    setTimer: (fn, ms) => { const t = { fn, ms }; timers.push(t); return t; },
    clearTimer: (t) => { const i = timers.indexOf(t as never); if (i >= 0) timers.splice(i, 1); },
  });
  return {
    sockets, timers, events, stop,
    get reconnects() { return reconnects; },
    setToken: (t: string) => { currentToken = t; },
    fire: () => timers.shift()!.fn(),
  };
}

test("delivers events while connected", () => {
  const h = harness();
  h.sockets[0].open();
  h.sockets[0].send({ machine_code: "LOOM-4", state: "breakdown" });
  assert.deepEqual(h.events, [{ machine_code: "LOOM-4", state: "breakdown" }]);
  assert.equal(h.reconnects, 0, "the first open is not a reconnect");
});

test("reconnects after the server goes away, with backoff, then asks the page to resync", () => {
  const h = harness();
  h.sockets[0].open();
  h.sockets[0].drop();                                     // backend restarted
  assert.equal(h.timers[0].ms, BACKOFF_MS[0]);
  h.fire();                                                // attempt 1 fails (backend still starting)
  h.sockets[1].drop();
  assert.equal(h.timers[0].ms, BACKOFF_MS[1]);
  h.fire();                                                // attempt 2 succeeds
  h.sockets[2].open();
  assert.equal(h.reconnects, 1, "page is told to re-fetch what it missed");
  h.sockets[2].send({ machine_code: "LOOM-4", state: "idle" });
  assert.deepEqual(h.events.at(-1), { machine_code: "LOOM-4", state: "idle" });
  h.sockets[2].drop();                                     // backoff starts over after a good connection
  assert.equal(h.timers[0].ms, BACKOFF_MS[0]);
});

test("keeps retrying at the longest backoff, and rebuilds the URL with the current token", () => {
  const h = harness("old");
  h.sockets[0].drop();                                     // backend down when the page loads
  for (let i = 0; i < BACKOFF_MS.length + 3; i++) { h.fire(); h.sockets.at(-1)!.drop(); }
  assert.equal(h.timers[0].ms, BACKOFF_MS.at(-1));
  h.setToken("new");
  h.fire();
  assert.equal(h.sockets.at(-1)!.url, "ws://host/ws/floor?token=new");
  h.sockets.at(-1)!.open();
  assert.equal(h.reconnects, 1, "first successful open after failures resyncs too");
});

test("stops on 4401 (bad session): retrying can't help", () => {
  const h = harness();
  h.sockets[0].drop(UNAUTHORIZED_CLOSE);
  assert.equal(h.timers.length, 0);
  assert.equal(h.sockets.length, 1);
});

test("React StrictMode double mount: the first socket is closed while connecting, the second one gets the events", () => {
  const sockets: FakeSocket[] = [];
  const events: unknown[] = [];
  const timers: unknown[] = [];
  const subscribe = () =>
    openFloorSocket({
      url: () => "ws://host/ws/floor?token=t",
      onEvent: (e) => events.push(e),
      createSocket: (url) => { const s = new FakeSocket(url); sockets.push(s); return s; },
      setTimer: (fn, ms) => { timers.push({ fn, ms }); return timers.at(-1); },
      clearTimer: () => {},
    });
  const stopFirst = subscribe();                         // mount
  stopFirst();                                           // StrictMode cleanup, before the handshake finished
  subscribe();                                           // mount again
  sockets[1].open();
  sockets[1].send({ machine_code: "LOOM-4", state: "breakdown", ended_at: null });
  assert.equal(sockets[0].closedByClient, true);
  assert.equal(timers.length, 0, "the deliberately closed first socket does not schedule a reconnect");
  assert.deepEqual(events, [{ machine_code: "LOOM-4", state: "breakdown", ended_at: null }]);
});

test("unsubscribe closes the socket and cancels a pending retry", () => {
  const h = harness();
  h.sockets[0].open();
  h.stop();
  assert.ok(h.sockets[0].closedByClient);
  assert.equal(h.timers.length, 0, "closing on purpose does not schedule a reconnect");

  const h2 = harness();
  h2.sockets[0].drop();                                    // a retry is pending...
  assert.equal(h2.timers.length, 1);
  h2.stop();                                               // ...and the page unmounts
  assert.equal(h2.timers.length, 0);
  assert.equal(h2.sockets.length, 1, "no new socket after unsubscribe");
});

test("stops on 4403 (role may not listen) and reports why; reports open and reconnecting", () => {
  const statuses: SocketStatus[] = [];
  const sockets: FakeSocket[] = [];
  const timers: (() => void)[] = [];
  openFloorSocket({
    url: () => "ws://host/ws/alerts?token=t",
    onEvent: () => {},
    onStatus: (s) => statuses.push(s),
    createSocket: (url) => { const s = new FakeSocket(url); sockets.push(s); return s; },
    setTimer: (fn) => { timers.push(fn); return fn; },
    clearTimer: () => {},
  });
  sockets[0].open();
  sockets[0].drop();
  timers.shift()!();
  sockets[1].drop(FORBIDDEN_CLOSE);
  assert.deepEqual(statuses, ["open", "reconnecting", "forbidden"]);
  assert.equal(timers.length, 0);
  assert.equal(sockets.length, 2);
});
