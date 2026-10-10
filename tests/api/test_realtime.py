"""Realtime: machine-state change in PostgreSQL -> NOTIFY -> listener -> /ws/floor clients.

Runs a real uvicorn server in a thread (a real socket, the real lifespan) and talks to it with the
`websockets` sync client, whose recv(timeout=) keeps every wait bounded.
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
import uuid

import httpx
import psycopg
import pytest
import uvicorn
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from app.realtime import Broadcaster
from tests.api.conftest import load_mock
from tests.conftest import TEST_URL

TIMEOUT = 2.0


def wait_until(cond, timeout: float = TIMEOUT, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.02)


@pytest.fixture(scope="module")
def live(app):                      # `app` points settings at the freshly seeded test DB
    from app.main import create_app
    server_app = create_app()       # own instance: its own pool, listener and broadcaster
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(server_app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_until(lambda: server.started, 10, "uvicorn to start")
    wait_until(server_app.state.floor_listener.connected.is_set, 5, "LISTEN")
    yield server_app, f"ws://127.0.0.1:{port}/ws/floor"
    server.should_exit = True
    thread.join(timeout=5)
    assert not thread.is_alive(), "server (and floor listener) did not shut down"


@pytest.fixture(scope="module")
def token(client) -> str:
    res = client.post("/api/auth/login", json={"email": "floor@everest.test", "password": "demo1234"})
    return res.json()["token"]


def subscribe(live, token: str):
    app, url = live
    before = len(app.state.floor_broadcaster)
    ws = connect(f"{url}?token={token}", open_timeout=TIMEOUT)
    wait_until(lambda: len(app.state.floor_broadcaster) > before, what="subscription")
    return ws


def notify(payload: dict) -> None:
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("SELECT pg_notify('loomledger_floor', %s)", (json.dumps(payload),))


# ---------- auth ----------
@pytest.mark.parametrize("query", ["", "?token=", "?token=garbage.token.here"])
def test_bad_or_missing_token_closes_4401(live, query):
    with connect(live[1] + query, open_timeout=TIMEOUT) as ws:
        with pytest.raises(ConnectionClosed) as closed:
            ws.recv(timeout=TIMEOUT)
    assert closed.value.rcvd.code == 4401


# ---------- relay ----------
def test_notify_reaches_every_client(live, token):
    payload = {"machine_id": 1, "machine_code": "LOOM-1", "state": "idle", "reason": None,
               "started_at": "2026-10-10T08:00:00+05:30", "ended_at": None}
    with subscribe(live, token) as a, subscribe(live, token) as b:
        notify(payload)
        assert json.loads(a.recv(timeout=TIMEOUT)) == payload
        assert json.loads(b.recv(timeout=TIMEOUT)) == payload


def test_real_machine_state_change_matches_contract(live, token):
    """A breakdown recorded in machine_state_log arrives in the exact shape of ws_floor_event.json."""
    mock = load_mock("ws_floor_event")
    with psycopg.connect(TEST_URL) as conn:
        machine_id, code = conn.execute("SELECT id, code FROM machine WHERE code = %s",
                                        (mock["machine_code"],)).fetchone()
        prev = conn.execute("SELECT id, started_at FROM machine_state_log WHERE machine_id = %s AND ended_at IS NULL",
                            (machine_id,)).fetchone()
        conn.commit()
        with subscribe(live, token) as ws:
            with conn.transaction():
                at = conn.execute("SELECT greatest(now(), %s::timestamptz + interval '1 minute')",
                                  (prev[1] if prev else None,)).fetchone()[0]
                if prev:
                    conn.execute("UPDATE machine_state_log SET ended_at = %s WHERE id = %s", (at, prev[0]))
                new_id = conn.execute(
                    "INSERT INTO machine_state_log (machine_id, state, reason, started_at)"
                    " VALUES (%s, 'breakdown', %s, %s) RETURNING id", (machine_id, mock["reason"], at)).fetchone()[0]
            events = [json.loads(ws.recv(timeout=TIMEOUT)) for _ in range(2 if prev else 1)]
        # restore the seeded floor so other tests see the original state
        with conn.transaction():
            conn.execute("DELETE FROM machine_state_log WHERE id = %s", (new_id,))
            if prev:
                conn.execute("UPDATE machine_state_log SET ended_at = NULL WHERE id = %s", (prev[0],))

    opened = events[-1]
    assert set(opened) == set(mock)
    assert opened["machine_id"] == machine_id and opened["machine_code"] == code
    assert (opened["state"], opened["reason"], opened["ended_at"]) == ("breakdown", mock["reason"], None)
    assert opened["started_at"].endswith("+05:30")
    if prev:
        assert events[0]["ended_at"] == opened["started_at"]      # the closed row comes first


def test_starting_a_run_pushes_running_to_the_floor_board(live, token, reseed_after_module):
    """POST /api/production/weaving-runs marks the loom running in the same transaction -> ws events."""
    app, url = live
    base = url.replace("ws://", "http://").removesuffix("/ws/floor")
    with subscribe(live, token) as ws:
        res = httpx.post(f"{base}/api/production/weaving-runs", headers={"Authorization": f"Bearer {token}"},
                         json={"machine_code": "LOOM-6", "yarn_lot_code": "Y-103", "product_code": "GRG-TWL",
                               "meters_planned": 50, "idempotency_key": str(uuid.uuid4())}, timeout=TIMEOUT)
        assert res.status_code == 201, res.text
        events = [json.loads(ws.recv(timeout=TIMEOUT)) for _ in range(2)]
    closed, opened = events
    assert closed["machine_code"] == opened["machine_code"] == "LOOM-6"
    assert closed["ended_at"] == opened["started_at"]
    assert (opened["state"], opened["ended_at"]) == ("running", None)


def test_listener_reconnects_after_db_drops_it(live, token):
    app, _ = live
    listener = app.state.floor_listener
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        killed = conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                              " WHERE application_name = 'loomledger-floor-listener'"
                              "   AND datname = current_database()").fetchall()
    assert killed
    wait_until(lambda: not listener.connected.is_set(), what="listener to notice")
    wait_until(listener.connected.is_set, what="listener to reconnect")
    with subscribe(live, token) as ws:
        notify({"after": "reconnect"})
        assert json.loads(ws.recv(timeout=TIMEOUT)) == {"after": "reconnect"}


def test_disconnected_clients_are_removed(live, token):
    app, _ = live
    before = len(app.state.floor_broadcaster)
    with subscribe(live, token):
        assert len(app.state.floor_broadcaster) == before + 1
    wait_until(lambda: len(app.state.floor_broadcaster) == before, what="unsubscribe")


# ---------- broadcaster (unit) ----------
def test_slow_subscriber_is_dropped_without_blocking_others():
    async def scenario():
        b = Broadcaster(queue_size=2)
        slow, fast = b.subscribe(), b.subscribe()
        for i in range(3):
            b.publish(f"m{i}")
            assert fast.queue.get_nowait() == f"m{i}"      # fast keeps up
        assert len(b) == 1                                  # slow fell 2 behind and was dropped
        assert slow.queue.get_nowait() is None              # ...and told to close
        b.publish("after")
        assert slow.queue.empty() and fast.queue.get_nowait() == "after"
    asyncio.run(scenario())
