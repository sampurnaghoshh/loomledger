"""The benchmark script keeps working, stays read-only, and reports every demo query (one quick run in CI)."""
from __future__ import annotations

import pytest

from scripts import benchmark
from tests.conftest import TEST_URL

DEMO_QUERIES = ("find_cause", "recall_scope", "recall_impact", "lot_ancestors", "stock_on_hand", "mass_balance",
                "buyer_order_status")


def test_benchmark_is_read_only_and_reports_every_demo_query(fresh_db, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    out = tmp_path / "BENCHMARK.md"
    assert benchmark.main(["--runs", "1", "--warmup", "0", "--out", str(out)]) == 0    # 1 = row counts changed
    report = out.read_text(encoding="utf-8")
    for name in DEMO_QUERIES:
        assert f"`{name}(" in report, name
    assert "## Index use" in report and "## Data size (exact row counts)" in report


def test_runs_must_be_odd_so_the_median_is_measured():
    with pytest.raises(SystemExit):
        benchmark.main(["--runs", "50"])
