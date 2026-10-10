"""Finance: mass balance + true cost per roll. Exact values vs the DB-exported mocks, and cross-checked
against seed/scenario.py's independent model — no demo number is typed here."""
from __future__ import annotations

from datetime import timedelta

import psycopg
import pytest
from psycopg.rows import dict_row

from seed import scenario as S
from tests.api.conftest import apply_story_recall, assert_same_shape, bearer, load_mock, login
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")
BALANCE, COSTS = "/api/finance/mass-balance", "/api/finance/roll-costs"
COST_KEYS = ("lot_code", "qty_m", "material", "machine", "labour", "chemicals", "total", "cost_per_m")


def q(sql: str, params: tuple = ()) -> list[dict]:
    with psycopg.connect(TEST_URL, row_factory=dict_row, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {role: bearer(login(client, f"{role}@everest.test")) for role in ("owner", "accounts", "qc", "store")}


# ---------- mass balance ----------
def test_mass_balance_matches_contract(client, auth):
    res = client.get(BALANCE, headers=auth["accounts"])
    assert res.status_code == 200, res.text
    mock = load_mock("finance_mass_balance")
    assert_same_shape(res.json(), mock)
    assert res.json() == mock


def test_mass_balance_finds_the_leaky_loom(client, auth):
    body = client.get(BALANCE, headers=auth["owner"]).json()
    worst, rest = body["by_machine"][0], body["by_machine"][1:]
    ended_runs = q("""SELECT count(*) AS n FROM process_run r JOIN machine m ON m.id = r.machine_id
                       WHERE m.code = %s AND r.stage = 'weaving' AND r.ended_at IS NOT NULL""", (S.LEAKY_MACHINE,))[0]["n"]
    assert worst["machine_code"] == S.LEAKY_MACHINE
    assert worst["unaccounted_kg"] == float(S.LEAKY_EXTRA_KG * ended_runs)
    assert all(m["unaccounted_kg"] == 0 for m in rest)
    assert body["totals"]["unaccounted_kg"] == worst["unaccounted_kg"]                 # all of it on one loom


def test_mass_balance_closes(client, auth):
    t = client.get(BALANCE, headers=auth["owner"]).json()["totals"]
    assert t["issued_kg"] == pytest.approx(t["fabric_kg"] + t["waste_kg"] + t["wip_kg"] + t["unaccounted_kg"])
    assert t["unaccounted_pct"] == round(100 * t["unaccounted_kg"] / t["issued_kg"], 2)


def test_mass_balance_window_is_consistent(client, auth):
    first = q("""SELECT min((started_at AT TIME ZONE 'Asia/Kolkata')::date) AS d
                   FROM process_run WHERE stage = 'weaving'""")[0]["d"]
    window = {"from": (first + timedelta(days=2)).isoformat(), "to": (first + timedelta(days=5)).isoformat()}
    body = client.get(BALANCE, params=window, headers=auth["owner"]).json()
    assert body["from"] == f"{window['from']}T00:00:00+05:30" and body["to"] == f"{window['to']}T00:00:00+05:30"
    whole = client.get(BALANCE, headers=auth["owner"]).json()["totals"]
    assert 0 < body["totals"]["issued_kg"] < whole["issued_kg"]
    assert body["totals"]["issued_kg"] == pytest.approx(sum(m["issued_kg"] for m in body["by_machine"]))
    assert body["totals"]["unaccounted_kg"] == pytest.approx(sum(m["unaccounted_kg"] for m in body["by_machine"]))


def test_first_run_at_is_the_earliest_run_in_the_window(client, auth):
    first = q("SELECT min(started_at) AS t FROM process_run WHERE stage = 'weaving'")[0]["t"]
    assert client.get(BALANCE, headers=auth["owner"]).json()["first_run_at"] == first.isoformat()
    month = {"from": S.ANCHOR_DATE.replace(day=1).isoformat(), "to": S.ANCHOR_DATE.isoformat()}
    in_month = q("""SELECT min(started_at) AS t FROM process_run WHERE stage = 'weaving'
                     AND started_at >= %s::timestamptz AND started_at < %s::timestamptz""", (month["from"], month["to"]))[0]["t"]
    assert client.get(BALANCE, params=month, headers=auth["owner"]).json()["first_run_at"] == in_month.isoformat()


def test_mass_balance_empty_window_is_zero(client, auth):
    body = client.get(BALANCE, params={"from": "2001-01-01", "to": "2001-02-01"}, headers=auth["owner"]).json()
    assert body["by_machine"] == [] and body["first_run_at"] is None
    assert body["totals"]["issued_kg"] == 0 and body["totals"]["unaccounted_pct"] is None


@pytest.mark.parametrize("params,field", [({"from": "soon"}, "from"),
                                          ({"from": S.ANCHOR_DATE.isoformat(), "to": "2001-01-01"}, "from")])
def test_mass_balance_bad_window_is_422(client, auth, params, field):
    res = client.get(BALANCE, params=params, headers=auth["owner"])
    assert res.status_code == 422 and field in res.json()["error"]["fields"]


# ---------- roll costs ----------
def test_roll_costs_before_recall_match_contract_costs(client, auth):
    res = client.get(COSTS, params={"order_code": "SO-0412"}, headers=auth["accounts"])
    assert res.status_code == 200, res.text
    mock = load_mock("finance_roll_costs_SO-0412")
    assert_same_shape(res.json(), mock)
    # costs never change with a recall; custody/status do (the mock was exported after it)
    assert [{k: r[k] for k in COST_KEYS} for r in res.json()] == [{k: r[k] for k in COST_KEYS} for r in mock]


def test_y112_roll_costs_match_the_independent_model(client, auth):
    rows = {r["lot_code"]: r for r in client.get(COSTS, params={"order_code": "SO-0412"}, headers=auth["owner"]).json()}
    y112 = [code for code in S.Y112_ROLLS if code in rows or f"{code}-G" in rows]
    assert y112
    for code in y112:
        finished = code in rows
        row = rows[code] if finished else rows[f"{code}-G"]
        assert row["total"] == float(S.expected_y112_roll_cost(finished).quantize(S.D("0.01"))), code


def test_roll_costs_after_recall_match_contract(client, auth):
    apply_story_recall()
    res = client.get(COSTS, params={"order_code": "SO-0412"}, headers=auth["owner"])
    assert res.json() == load_mock("finance_roll_costs_SO-0412")


def test_roll_costs_unknown_order_is_404(client, auth):
    res = client.get(COSTS, params={"order_code": "SO-9999"}, headers=auth["owner"])
    assert res.status_code == 404 and res.json()["error"]["fields"] == {"order_code": "not found"}


def test_roll_costs_need_an_order(client, auth):
    res = client.get(COSTS, headers=auth["owner"])
    assert res.status_code == 422 and "order_code" in res.json()["error"]["fields"]


# ---------- access ----------
@pytest.mark.parametrize("path", [BALANCE, f"{COSTS}?order_code=SO-0412"])
@pytest.mark.parametrize("role", ["qc", "store"])
def test_wrong_role_is_403(client, auth, path, role):
    assert client.get(path, headers=auth[role]).status_code == 403


@pytest.mark.parametrize("path", [BALANCE, f"{COSTS}?order_code=SO-0412"])
def test_needs_token(client, path):
    assert client.get(path).status_code == 401
