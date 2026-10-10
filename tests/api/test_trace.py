"""Trace (Act 2): find-cause and the genealogy graph, through the API. Read-only, before any recall."""
from __future__ import annotations

import pytest

from seed import scenario as S
from tests.api.conftest import assert_same_shape, bearer, load_mock, login

FIND, GRAPH = "/api/trace/find-cause", "/api/trace/graph"


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {role: bearer(login(client, f"{role}@everest.test")) for role in ("owner", "qc", "store")}


# ---------- find cause ----------
def test_find_cause_matches_contract(client, auth):
    res = client.post(FIND, json={"lot_codes": S.REJECTED_ROLLS}, headers=auth["qc"])
    assert res.status_code == 200, res.text
    mock = load_mock("trace_find_cause")
    assert_same_shape(res.json(), mock)
    assert res.json() == mock


def test_find_cause_equals_the_golden_expectations(client, auth):
    body = client.post(FIND, json={"lot_codes": S.REJECTED_ROLLS}, headers=auth["store"]).json()
    causes = {f["factor_label"]: f for f in body["factors"]}
    for label, (insp_in, rej_in, rate_in, insp_out, rej_out, rate_out, verdict) in S.EXPECTED_FIND_CAUSE.items():
        f = causes[label]
        assert (f["inspected_through"], f["rejected_through"], f["rate_through_pct"]) == (insp_in, rej_in, float(rate_in)), label
        assert (f["inspected_outside"], f["rejected_outside"], f["rate_outside_pct"]) == (insp_out, rej_out, float(rate_out)), label
        assert f["verdict"] == verdict, label
    root = next(label for label, e in S.EXPECTED_FIND_CAUSE.items() if e[-1] == "root_cause")
    assert body["factors"][0]["factor_label"] == root                      # the DB's ranking, untouched


# ---------- graph ----------
def test_ancestor_graph_matches_contract(client, auth):
    res = client.post(GRAPH, json={"lot_codes": S.REJECTED_ROLLS, "direction": "up"}, headers=auth["owner"])
    assert res.status_code == 200, res.text
    mock = load_mock("trace_graph_ancestors")
    assert_same_shape(res.json(), mock)
    assert res.json() == mock


def test_descendant_graph_matches_contract(client, auth):
    res = client.get(f"/api/trace/lots/{S.Y112}/descendants", headers=auth["qc"])
    assert res.status_code == 200, res.text
    mock = load_mock("trace_graph_descendants")
    assert_same_shape(res.json(), mock)
    assert res.json() == mock


def test_graph_down_is_the_descendant_graph(client, auth):
    down = client.post(GRAPH, json={"lot_codes": [S.Y112], "direction": "down"}, headers=auth["qc"]).json()
    desc = client.get(f"/api/trace/lots/{S.Y112}/descendants", headers=auth["qc"]).json()
    assert (down["nodes"], down["edges"]) == (desc["nodes"], desc["edges"])


def test_graph_edges_only_join_listed_nodes(client, auth):
    body = client.post(GRAPH, json={"lot_codes": S.REJECTED_ROLLS}, headers=auth["qc"]).json()   # direction defaults to up
    codes = {n["code"] for n in body["nodes"]}
    assert set(S.REJECTED_ROLLS) <= codes and S.Y112 in codes
    assert all(e["from"] in codes and e["to"] in codes for e in body["edges"])


# ---------- errors ----------
@pytest.mark.parametrize("path,body", [(FIND, {"lot_codes": ["R-1201", "R-9999"]}),
                                       (GRAPH, {"lot_codes": ["R-9999"]})])
def test_unknown_lot_is_404(client, auth, path, body):
    res = client.post(path, json=body, headers=auth["qc"])
    assert res.status_code == 404 and "R-9999" in res.json()["error"]["fields"]["lot_codes"]


def test_unknown_lot_descendants_is_404(client, auth):
    res = client.get("/api/trace/lots/Y-999/descendants", headers=auth["qc"])
    assert res.status_code == 404 and "Y-999" in res.json()["error"]["fields"]["lot_code"]


@pytest.mark.parametrize("path,body,field", [
    (FIND, {"lot_codes": []}, "lot_codes"), (FIND, {}, "lot_codes"),
    (FIND, {"lot_codes": ["R-1201", "R-1201"]}, "lot_codes"),
    (GRAPH, {"lot_codes": ["R-1201"], "direction": "sideways"}, "direction")])
def test_bad_body_is_422(client, auth, path, body, field):
    res = client.post(path, json=body, headers=auth["qc"])
    assert res.status_code == 422 and field in res.json()["error"]["fields"]


@pytest.mark.parametrize("method,path,body", [("post", FIND, {"lot_codes": ["R-1201"]}),
                                              ("post", GRAPH, {"lot_codes": ["R-1201"]}),
                                              ("get", f"/api/trace/lots/{S.Y112}/descendants", None)])
def test_needs_token(client, method, path, body):
    res = client.post(path, json=body) if method == "post" else client.get(path)
    assert res.status_code == 401
