"""Real-time floor board: PostgreSQL LISTEN/NOTIFY relayed to WebSocket clients.

    machine_state_log trigger --pg_notify('loomledger_floor')--> FloorListener --> Broadcaster --> /ws/floor clients

- The database builds the payload (migration 006 = docs/api-mocks/ws_floor_event.json); we relay it untouched.
- FloorListener owns ONE dedicated connection (not from the request pool). It is a sync psycopg connection in a
  worker thread: async psycopg cannot run on the ProactorEventLoop uvicorn uses on Windows.
  It reconnects with exponential backoff if PostgreSQL drops and stops cleanly within `poll_s`.
- Broadcaster gives each client a bounded queue: publishing never waits on a socket, and a client that
  falls `queue_size` messages behind is disconnected (1013 "try again later") instead of slowing everyone.
- Events sent while the listener is reconnecting are lost; clients re-fetch GET /api/floor/machines on (re)connect.

Owner alerts (016) use the same machinery on their OWN channel and socket, so floor clients never see them:

    recall commit / breakdown --pg_notify('loomledger_alerts')--> listener --> Broadcaster --> /ws/alerts (owner, qc)

Alerts are live only: nothing is replayed on connect.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable

import psycopg
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from psycopg import sql
from psycopg_pool import ConnectionPool
from starlette.concurrency import run_in_threadpool

from app.auth import find_user, has_permission, read_token
from app.errors import ApiError

log = logging.getLogger("loomledger.realtime")

FLOOR_CHANNEL = "loomledger_floor"
ALERTS_CHANNEL = "loomledger_alerts"
ALERT_PERMISSION = "alerts.listen"      # 017 role_permission (owner, qc)
WS_UNAUTHENTICATED = 4401      # app-defined close code (4000-4999): bad/missing/expired token
WS_FORBIDDEN = 4403            # signed in, but this role may not listen here
WS_TRY_AGAIN_LATER = 1013      # client too slow to keep up


# ---------- fan-out ----------
class Subscriber:
    def __init__(self, queue_size: int):
        self.queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=queue_size)   # None = "you were dropped"


class Broadcaster:
    """In-process fan-out. Call publish() only from the event loop thread."""

    def __init__(self, queue_size: int = 100):
        self._queue_size = queue_size
        self._subscribers: set[Subscriber] = set()

    def __len__(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> Subscriber:
        sub = Subscriber(self._queue_size)
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subscribers.discard(sub)

    def publish(self, message: str) -> None:
        for sub in list(self._subscribers):
            try:
                sub.queue.put_nowait(message)
            except asyncio.QueueFull:
                log.warning("dropping slow floor client (%d messages behind)", self._queue_size)
                self.unsubscribe(sub)
                while not sub.queue.empty():
                    sub.queue.get_nowait()
                sub.queue.put_nowait(None)


# ---------- LISTEN ----------
class FloorListener:
    def __init__(self, conninfo: str, on_message: Callable[[str], None], *, channel: str = FLOOR_CHANNEL,
                 poll_s: float = 0.5, backoff_s: float = 0.5, max_backoff_s: float = 30.0):
        self._conninfo = conninfo
        self._on_message = on_message
        self._channel = channel
        self._poll_s = poll_s
        self._backoff_s = backoff_s
        self._max_backoff_s = max_backoff_s
        self._stop = threading.Event()
        self.connected = threading.Event()     # set while LISTEN is active (used by /api/health and tests)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop.clear()
        self._task = asyncio.create_task(asyncio.to_thread(self._run), name=f"listener-{self._channel}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task          # the thread notices _stop within poll_s (or the current backoff wait)
            self._task = None

    def _deliver(self, payload: str) -> None:
        assert self._loop is not None
        self._loop.call_soon_threadsafe(self._on_message, payload)

    def _run(self) -> None:
        backoff = self._backoff_s
        while not self._stop.is_set():
            try:
                with psycopg.connect(self._conninfo, autocommit=True, connect_timeout=5,
                                     application_name=f"loomledger-{self._channel.removeprefix('loomledger_')}-listener") as conn:
                    conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(self._channel)))
                    self.connected.set()
                    log.info("listening on %s", self._channel)
                    backoff = self._backoff_s
                    while not self._stop.is_set():
                        for note in conn.notifies(timeout=self._poll_s):
                            self._deliver(note.payload)
            except psycopg.Error as exc:
                was_connected = self.connected.is_set()
                self.connected.clear()
                log.warning("floor listener %s (%s); reconnecting in %.1fs",
                            "lost connection" if was_connected else "cannot connect",
                            type(exc).__name__, backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, self._max_backoff_s)
            except Exception:
                self.connected.clear()
                if self._loop is not None and self._loop.is_closed():
                    break             # the app is shutting down
                log.exception("floor listener crashed; restarting in %.1fs", backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, self._max_backoff_s)
        self.connected.clear()
        log.info("floor listener stopped")


# ---------- WebSocket ----------
router = APIRouter(tags=["floor"])


def _authenticate(pool: ConnectionPool, token: str | None, permission: str | None = None) -> dict | None:
    """The user behind the token (None = 4401); with `permission`, user["allowed"] says whether they hold it."""
    if not token:
        return None
    try:
        user_id = read_token(token)
    except ApiError:
        return None
    with pool.connection() as conn:
        user = find_user(conn, user_id)
        if user is not None:
            user["allowed"] = permission is None or has_permission(conn, user["role"], permission)
        return user


async def _pump(websocket: WebSocket, sub: Subscriber) -> None:
    while True:
        message = await sub.queue.get()
        if message is None:
            await websocket.close(code=WS_TRY_AGAIN_LATER, reason="too slow")
            return
        await websocket.send_text(message)


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    while True:
        if (await websocket.receive())["type"] == "websocket.disconnect":
            return


async def _stream(websocket: WebSocket, token: str | None, broadcaster: Broadcaster,
                  permission: str | None = None) -> None:
    await websocket.accept()       # accept first so the browser actually receives the 4401 / 4403 close code
    user = await run_in_threadpool(_authenticate, websocket.app.state.pool, token, permission)
    if user is None:
        await websocket.close(code=WS_UNAUTHENTICATED, reason="unauthenticated")
        return
    if not user["allowed"]:
        await websocket.close(code=WS_FORBIDDEN, reason="forbidden")
        return

    sub = broadcaster.subscribe()
    tasks = {asyncio.create_task(_pump(websocket, sub)), asyncio.create_task(_wait_for_disconnect(websocket))}
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        broadcaster.unsubscribe(sub)
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                pass               # socket already gone


@router.websocket("/ws/floor")
async def floor_events(websocket: WebSocket, token: str | None = None) -> None:
    """Stream of machine-state events. Auth: ?token=<login token> (browsers can't set WS headers)."""
    await _stream(websocket, token, websocket.app.state.floor_broadcaster)


@router.websocket("/ws/alerts")
async def owner_alerts(websocket: WebSocket, token: str | None = None) -> None:
    """Live owner alerts (016): committed recalls and breakdowns. Needs alerts.listen (017); nothing is replayed."""
    await _stream(websocket, token, websocket.app.state.alerts_broadcaster, ALERT_PERMISSION)
