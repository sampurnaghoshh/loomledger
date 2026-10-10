"""Act 2 through the API: QC rejects R-1201..R-1203 via POST /api/quality/inspections, and Find Cause
then sees exactly the numbers the golden test expects (seed/scenario.py EXPECTED_FIND_CAUSE).

The database is seeded with qc_story_rejects=False, so the three story rolls wait for QC instead of
being pre-rejected by the seed; everything else is the normal demo data.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from db.migrate import migrate, reset_schema
from seed import scenario as S
from seed.seed import seed
from tests.api.conftest import bearer, login
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")


@pytest.fixture(scope="module")
def story_pending_qc(app):
    with psycopg.connect(TEST_URL) as conn:
        reset_schema(conn)
        migrate(conn)
        seed(conn, qc_story_rejects=False)


def test_rejecting_the_story_rolls_via_api_reproduces_find_cause(client, story_pending_qc):
    qc = bearer(login(client, "qc@everest.test"))
    queue = [q["lot_code"] for q in client.get("/api/quality/queue", headers=qc).json()]
    assert set(S.REJECTED_ROLLS) <= set(queue)                       # waiting for QC, not pre-rejected

    for code in S.REJECTED_ROLLS:
        res = client.post("/api/quality/inspections", headers=qc, json={
            "lot_code": code, "result": "reject", "defect_type": S.DEFECT,
            "defect_meters": float(S.ROLL_LENGTH_M), "idempotency_key": str(uuid.uuid4())})
        assert res.status_code == 201, res.text

    with psycopg.connect(TEST_URL, row_factory=dict_row) as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM lot WHERE code = ANY(%s)", (S.REJECTED_ROLLS,))]
        causes = {r["factor_label"]: r for r in conn.execute("SELECT * FROM find_cause(%s)", (ids,))}
        totals = conn.execute(
            "SELECT count(*) AS n, count(*) FILTER (WHERE result = 'reject') AS rejected FROM v_latest_qc").fetchone()
        custody = {r["lot_code"]: r["custody"] for r in conn.execute(
            "SELECT lot_code, custody FROM v_roll_custody WHERE lot_code = ANY(%s)", (S.REJECTED_ROLLS,))}

    for label, (insp_in, rej_in, rate_in, insp_out, rej_out, rate_out, verdict) in S.EXPECTED_FIND_CAUSE.items():
        c = causes[label]
        assert (c["inspected_through"], c["rejected_through"], c["rate_through_pct"]) == (insp_in, rej_in, rate_in), label
        assert (c["inspected_outside"], c["rejected_outside"], c["rate_outside_pct"]) == (insp_out, rej_out, rate_out), label
        assert c["verdict"] == verdict, label
    assert (totals["n"], totals["rejected"]) == (S.EXPECTED_INSPECTED_TOTAL, S.EXPECTED_REJECTED_TOTAL)
    assert custody == {code: "rejected" for code in S.REJECTED_ROLLS}
