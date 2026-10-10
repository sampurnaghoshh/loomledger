"""The demo calendar: the mill works Monday–Saturday, and nothing locked depends on the day you present.

A presentation can happen on a later day than the story (e.g. a Sunday after the Saturday in the seed).
Applying the recall then must not move the revised promise dates: they come from the promised dates and the
remake arithmetic (add_working_days, IMMUTABLE), never from the clock.
"""
from __future__ import annotations

from datetime import date, timedelta

import psycopg
from psycopg.rows import dict_row

from db.migrate import migrate, reset_schema
from seed import scenario as S
from seed.seed import seed
from tests.conftest import TEST_URL


def test_last_working_day_maps_sunday_to_saturday():
    with psycopg.connect(TEST_URL) as conn:
        monday = next(S.ANCHOR_DATE + timedelta(days=i) for i in range(7) if (S.ANCHOR_DATE + timedelta(days=i)).isoweekday() == 1)
        for i in range(7):
            d = monday + timedelta(days=i)
            expected = d - timedelta(days=1) if d.isoweekday() == 7 else d
            assert conn.execute("SELECT last_working_day(%s)", (d,)).fetchone()[0] == expected, d


def test_recall_dates_do_not_depend_on_when_it_is_applied():
    """Story placed a week before the real clock; recall applied 'late' -> same delays and dates as the model."""
    anchor = S.ANCHOR_DATE - timedelta(days=7)
    assert anchor.isoweekday() != 7
    try:
        with psycopg.connect(TEST_URL, row_factory=dict_row) as conn:
            reset_schema(conn)
            migrate(conn)
            seed(conn, anchor)
            assert conn.execute("SELECT (now() AT TIME ZONE 'Asia/Kolkata')::date AS d").fetchone()["d"] > anchor
            with conn.transaction():
                conn.execute("SELECT apply_recall(id, 'calendar test', NULL) FROM lot WHERE code = %s", (S.Y112,))
            orders = {r["code"]: r for r in conn.execute(
                "SELECT code, promised_date, revised_promise_date, working_days_between(promised_date, revised_promise_date) AS delay "
                "FROM sales_order").fetchall()}
        for code, e in S.expected_order_impact(anchor).items():
            assert (orders[code]["promised_date"], orders[code]["revised_promise_date"]) == (e["promised"], e["revised"]), code
            assert orders[code]["delay"] == e["delay_days"], code
    finally:
        with psycopg.connect(TEST_URL) as conn:              # leave the default story for whoever runs next
            reset_schema(conn)
            migrate(conn)
            seed(conn)


def test_default_story_delays_are_the_locked_ones():
    model = S.expected_order_impact()
    assert [(e["delay_days"], e["revised"]) for e in model.values()] == \
        [(e["delay_days"], e["revised"]) for e in S.expected_order_impact(S.ANCHOR_DATE).values()]
    assert all(isinstance(e["revised"], date) for e in model.values())
