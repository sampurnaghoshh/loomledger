"""Owner alerts (migration 016): pg_notify('loomledger_alerts') -> listener -> /ws/alerts (owner, qc).

The recall alert is sent by PostgreSQL at COMMIT of apply_recall: a rolled-back recall never alerts and
re-applying the same recall (idempotent) never alerts twice. Payloads equal docs/api-mocks/ws_alert_*.json and the
independent scenario.py numbers. Floor clients never receive alerts (separate channel and socket).
"""
from __future__ import annotations

import json
import time
from decimal import Decimal as D

import psycopg
import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from seed import scenario as S
from tests.api.conftest import assert_same_shape, load_mock
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")
TIMEOUT = 3.0
QUIET = 1.0                        # how long "nothing arrives" is watched for
REASON = "Colour mismatch traced to yarn lot Y-112"


def wait_until(cond, timeout: float = TIMEOUT, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.02)


@pytest.fixture(scope="module")
def live(live_server):
    app, base = live_server
    return app, base.replace("http://", "ws://")


@pytest.fixture(scope="module")
def tokens(client) -> dict[str, str]:
    out = {}
    for role in ("owner", "qc", "floor"):
        res = client.post("/api/auth/login", json={"email": f"{role}@everest.test", "password": "demo1234"})
        out[role] = res.json()["token"]
    return out


def subscribe(live, token: str, path: str = "/ws/alerts"):
    app, base = live
    broadcaster = app.state.alerts_broadcaster if path == "/ws/alerts" else app.state.floor_broadcaster
    before = len(broadcaster)
    ws = connect(f"{base}{path}?token={token}", open_timeout=TIMEOUT)
    wait_until(lambda: len(broadcaster) > before, what="subscription")
    return ws


def nothing_arrives(ws) -> bool:
    try:
        ws.recv(timeout=QUIET)
    except TimeoutError:
        return True
    return False


class Listen:
    """A plain LISTEN on the database: proves what PostgreSQL itself sends, independent of the API."""

    def __enter__(self):
        self.conn = psycopg.connect(TEST_URL, autocommit=True)
        self.conn.execute("LISTEN loomledger_alerts")
        return self

    def received(self, wait: float = QUIET) -> list[dict]:
        """Every alert PostgreSQL delivers within `wait` seconds."""
        out, deadline = [], time.monotonic() + wait
        while (left := deadline - time.monotonic()) > 0:
            for n in self.conn.notifies(timeout=left):
                out.append(json.loads(n.payload))
        return out

    def __exit__(self, *exc):
        self.conn.close()


def y112_id() -> int:
    with psycopg.connect(TEST_URL) as conn:
        return conn.execute("SELECT id FROM lot WHERE code = %s", (S.Y112,)).fetchone()[0]


# ---------- auth (no writes)
@pytest.mark.parametrize("query", ["", "?token=", "?token=garbage.token.here"])
def test_bad_or_missing_token_closes_4401(live, query):
    with connect(f"{live[1]}/ws/alerts{query}", open_timeout=TIMEOUT) as ws:
        with pytest.raises(ConnectionClosed) as closed:
            ws.recv(timeout=TIMEOUT)
    assert closed.value.rcvd.code == 4401


def test_roles_other_than_owner_and_qc_close_4403(live, tokens):
    with connect(f"{live[1]}/ws/alerts?token={tokens['floor']}", open_timeout=TIMEOUT) as ws:
        with pytest.raises(ConnectionClosed) as closed:
            ws.recv(timeout=TIMEOUT)
    assert closed.value.rcvd.code == 4403


def test_nothing_old_is_replayed_on_connect(live, tokens):
    with subscribe(live, tokens["owner"]) as ws:
        assert nothing_arrives(ws)


# ---------- the recall alert is sent by PostgreSQL only on COMMIT
def test_a_rolled_back_recall_never_alerts():
    with Listen() as listen, psycopg.connect(TEST_URL) as conn:
        with conn.transaction(force_rollback=True):
            conn.execute("SELECT apply_recall(%s, %s)", (y112_id(), REASON))
            assert listen.received(0.3) == []                    # deferred: nothing before commit either
        assert listen.received() == []
        assert conn.execute("SELECT count(*) FROM recall").fetchone()[0] == 0


def test_breakdown_alerts_once(client, live, tokens):
    with subscribe(live, tokens["owner"]) as alerts:
        res = client.post("/api/floor/machines/LOOM-4/state", json={"state": "breakdown", "reason": "Warp beam bearing failure"},
                          headers={"Authorization": f"Bearer {tokens['floor']}"})
        assert res.status_code == 200, res.text
        alert = json.loads(alerts.recv(timeout=TIMEOUT))
        assert_same_shape(alert, load_mock("ws_alert_breakdown"))
        mock = load_mock("ws_alert_breakdown")
        assert {k: alert[k] for k in ("kind", "machine_code", "machine_name", "reason")} == \
               {k: mock[k] for k in ("kind", "machine_code", "machine_name", "reason")}
        assert alert["started_at"] == res.json()["started_at"][:19] + "+05:30"
        assert nothing_arrives(alerts)                                      # one alert per breakdown
        # back to running: no alert
        client.post("/api/floor/machines/LOOM-4/state", json={"state": "running"},
                    headers={"Authorization": f"Bearer {tokens['floor']}"})
        assert nothing_arrives(alerts)


def test_floor_socket_never_carries_alerts(client, live, tokens):
    with subscribe(live, tokens["floor"], "/ws/floor") as floor:
        client.post("/api/floor/machines/LOOM-1/state", json={"state": "breakdown", "reason": "test"},
                    headers={"Authorization": f"Bearer {tokens['floor']}"})
        got = []
        try:
            while True:
                got.append(json.loads(floor.recv(timeout=QUIET)))
        except TimeoutError:
            pass
        assert got and all("kind" not in e and "machine_code" in e and "state" in e for e in got)
        client.post("/api/floor/machines/LOOM-1/state", json={"state": "running"},
                    headers={"Authorization": f"Bearer {tokens['floor']}"})


def test_committed_recall_alerts_once_with_the_story_numbers(client, live, tokens):
    qc = {"Authorization": f"Bearer {tokens['qc']}"}
    with Listen() as listen, subscribe(live, tokens["owner"]) as owner, subscribe(live, tokens["qc"]) as qc_ws:
        res = client.post("/api/recalls", json={"lot_code": S.Y112, "reason": REASON}, headers=qc)
        assert res.status_code == 201, res.text
        alert = json.loads(owner.recv(timeout=TIMEOUT))
        assert json.loads(qc_ws.recv(timeout=TIMEOUT)) == alert             # every alert client gets it
        assert listen.received() == [alert]                                  # PostgreSQL sent exactly one

        mock = load_mock("ws_alert_recall")
        assert_same_shape(alert, mock)
        assert {k: v for k, v in alert.items() if k != "applied_at"} == {k: v for k, v in mock.items() if k != "applied_at"}
        assert alert["applied_at"][:16] == res.json()["applied_at"][:16]

        # vs the independent scenario numbers
        scope = S.EXPECTED_SCOPE
        assert (alert["recall_code"], alert["root_lot_code"]) == (res.json()["recall_code"], S.Y112)
        assert [alert[k] for k in ("rolls_total", "rolls_rejected", "rolls_at_risk", "rolls_at_customer",
                                   "orders_affected", "buyers_affected")] == \
               [scope[k] for k in ("rolls_total", "rolls_rejected", "rolls_at_risk", "rolls_at_customer",
                                   "orders_affected", "buyers_affected")]
        assert [r for b in alert["at_buyers"] for r in b["rolls"]] == S.EXPECTED_AT_CUSTOMER
        impact = S.expected_order_impact()
        assert {o["order_code"]: (o["delay_days"], o["revised_promise_date"]) for o in alert["orders"]} == \
               {c: (v["delay_days"], v["revised"].isoformat()) for c, v in impact.items()}
        assert alert["delay_days"] == max(v["delay_days"] for v in impact.values())
        assert D(str(alert["total_exposure"])) == S.expected_money()["total_exposure"].quantize(D("0.01"))

        # re-applying the same recall (idempotent, 200) must not alert again
        again = client.post("/api/recalls", json={"lot_code": S.Y112, "reason": "pressed again"}, headers=qc)
        assert again.status_code == 200
        assert nothing_arrives(owner) and listen.received() == []
