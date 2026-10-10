"""QR roll passport + labels (F1). Built only from existing views/functions; checked against the contract mocks and
the independent scenario.py values, before and after the Y-112 recall; every error path."""
from __future__ import annotations

from decimal import Decimal as D

import psycopg
import pytest
from psycopg.rows import dict_row

from seed import scenario as S
from tests.api.conftest import apply_story_recall, assert_same_shape, bearer, load_mock, login
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")
ROLLS = S.PASSPORT_ROLLS                         # one Y-112 roll per banner: rejected / at_customer / passed / wip
ORDER_OF = {code: order for code, (_, _, order) in S.Y112_ROLLS.items()}


def passport_url(code: str) -> str:
    return f"/api/rolls/{code}/passport"


def buyer_name(order_code: str) -> str:
    party = next(o.buyer for o in S.ORDERS if o.code == order_code)
    with psycopg.connect(TEST_URL, row_factory=dict_row) as conn:
        return conn.execute("SELECT name FROM party WHERE code = %s", (party,)).fetchone()["name"]


def roll_of(code: str) -> str:
    return code.removesuffix("-G")               # the greige lot of a roll still on the loom


@pytest.fixture(scope="module")
def auth(client) -> dict:
    return bearer(login(client, "store@everest.test"))       # any signed-in user


@pytest.fixture(scope="module")
def clean(client, auth) -> str:
    return next(r["code"] for r in client.get("/api/rolls/labels", headers=auth).json()["rolls"] if not r["in_scope"])


# ---------- before the recall (read-only tests first; the module reseeds at the end)
def test_labels_match_contract_and_the_y112_family(client, auth):
    res = client.get("/api/rolls/labels", headers=auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body == load_mock("roll_labels_before")
    assert body["root"] == S.Y112                # the yarn lot behind the latest QC rejection
    in_scope = {r["code"]: r["custody"] for r in body["rolls"] if r["in_scope"]}
    expected = {(f"{c}-G" if custody == "wip" else c): custody for c, (_, custody, _) in S.Y112_ROLLS.items()}
    assert in_scope == expected                  # all 12, each where the story puts it
    clean = [r for r in body["rolls"] if not r["in_scope"]]
    assert len(clean) == 1 and clean[0]["custody"] == "passed_in_store"


@pytest.mark.parametrize("banner", list(ROLLS))
def test_passport_matches_contract_and_scenario(client, auth, banner):
    code = ROLLS[banner]
    res = client.get(passport_url(code), headers=auth)
    assert res.status_code == 200, res.text
    p = res.json()
    assert_same_shape(p, load_mock(f"roll_passport_{ROLLS['at_customer']}_before"))
    assert p == load_mock(f"roll_passport_{code}_before")
    assert (p["code"], p["custody"], p["recall"]) == (code, banner, None)

    # the family tree, oldest first: Y-112 bought from its supplier -> ... -> this roll
    first, last = p["lineage"][0], p["lineage"][-1]
    assert (first["lot_code"], first["kind"], first["run"]) == (S.Y112, "yarn", None) and first["receipt"]["supplier"]
    assert (last["lot_code"], last["depth"]) == (code, 0)
    assert all(step["run"] for step in p["lineage"][1:])          # every fabric step was made by a run

    order = ORDER_OF[roll_of(code)]
    assert (p["order"]["code"], p["order"]["buyer"]) == (order, buyer_name(order))
    assert p["order"]["revised_promise_date"] is None              # not re-promised before the recall


def test_banner_facts(client, auth):
    get = lambda code: client.get(passport_url(code), headers=auth).json()   # noqa: E731
    rejected = get(ROLLS["rejected"])
    assert rejected["qc"]["result"] == "reject" and rejected["qc"]["defect_type"]
    shipped = get(ROLLS["at_customer"])
    assert shipped["code"] in S.EXPECTED_AT_CUSTOMER and shipped["dispatch"]["invoice_code"]
    assert shipped["order"]["buyer"] == buyer_name(ORDER_OF[shipped["code"]])
    passed = get(ROLLS["passed_in_store"])
    assert passed["qc"]["result"] == "pass" and passed["dispatch"] is None
    wip = get(ROLLS["wip"])
    assert (wip["kind"], wip["qc"], wip["lineage"][-1]["run"]["ended_at"]) == ("greige", None, None)


def test_true_cost_is_lot_cost(client, auth):
    for banner in ("rejected", "at_customer", "passed_in_store"):
        cost = client.get(passport_url(ROLLS[banner]), headers=auth).json()["cost"]
        assert D(str(cost["total"])) == S.expected_y112_roll_cost(True).quantize(D("0.01")), banner
    wip = client.get(passport_url(ROLLS["wip"]), headers=auth).json()["cost"]
    assert D(str(wip["total"])) == D(str(wip["material"]))          # WIP carries material only


def test_clean_roll_is_outside_the_family(client, auth, clean):
    p = client.get(passport_url(clean), headers=auth).json()
    assert p == load_mock(f"roll_passport_{clean}_before")
    assert S.Y112 not in {s["lot_code"] for s in p["lineage"]}
    assert (p["custody"], p["status"], p["recall"]) == ("passed_in_store", "active", None)


# ---------- errors
def test_unknown_roll_is_404(client, auth):
    res = client.get(passport_url("R-9999"), headers=auth)
    assert res.status_code == 404 and res.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("code", ["Y-112", "abc", "R-12", "R-1204-X"])
def test_bad_roll_code_is_422(client, auth, code):
    res = client.get(passport_url(code), headers=auth)
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_FAILED"


def test_labels_unknown_root_is_404_and_bad_root_is_422(client, auth):
    assert client.get("/api/rolls/labels", params={"root": "Y-999"}, headers=auth).status_code == 404
    res = client.get("/api/rolls/labels", params={"root": "drop table"}, headers=auth)
    assert res.status_code == 422 and "root" in res.json()["error"]["fields"]


@pytest.mark.parametrize("path", [passport_url("R-1204"), "/api/rolls/labels"])
def test_needs_token(client, path):
    assert client.get(path).status_code == 401


# ---------- after the recall (writes: last in the module)
def test_after_the_recall_every_y112_roll_shows_it(client, auth, clean):
    apply_story_recall()
    impact = S.expected_order_impact()
    for banner, code in ROLLS.items():
        p = client.get(passport_url(code), headers=auth).json()
        assert p == load_mock(f"roll_passport_{code}_after"), code
        assert (p["recall"]["code"], p["recall"]["root_lot_code"]) == (f"RC-{S.Y112}", S.Y112)
        assert p["status"] == ("recalled" if banner == "at_customer" else "quarantined")
        assert p["custody"] == banner                                # custody is a fact; the recall freezes status
        assert p["order"]["revised_promise_date"] == impact[ORDER_OF[roll_of(code)]]["revised"].isoformat()

    untouched = client.get(passport_url(clean), headers=auth).json()
    assert untouched == load_mock(f"roll_passport_{clean}_after") == load_mock(f"roll_passport_{clean}_before")
    assert client.get("/api/rolls/labels", headers=auth).json() == load_mock("roll_labels_after")
