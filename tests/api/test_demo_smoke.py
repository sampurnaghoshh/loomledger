"""CI covers the whole demo: scripts/demo_smoke.py walks Acts 1-4 + close over HTTP and the ws,
against a real uvicorn server on a freshly seeded test database."""
from __future__ import annotations

import pytest

from scripts.demo_smoke import NOT_FRESH, Smoke
from tests.api.conftest import apply_story_recall
from tests.conftest import _fresh

pytestmark = pytest.mark.usefixtures("reseed_after_module")


@pytest.fixture(scope="module")
def fresh_story(live_server):
    _fresh().close()                 # the smoke insists on an un-recalled database
    return live_server[1]


def test_the_whole_demo_story_passes(fresh_story):
    lines: list[str] = []
    code = Smoke(fresh_story, out=lines.append).run()
    report = "\n".join(lines)
    assert code == 0, report
    assert not [line for line in lines if line.startswith("✗")] and "demo story OK" in report
    for act in ("Act 1", "Act 2", "Act 3", "Act 4", "Close"):
        assert f"✓ {act} ·" in report, act


def test_refuses_a_database_that_is_not_fresh(fresh_story):
    apply_story_recall()             # idempotent: whatever ran before, the recall is now applied
    lines: list[str] = []
    assert Smoke(fresh_story, out=lines.append).run() == NOT_FRESH
    assert "run ./scripts/reset_demo.sh first" in "\n".join(lines)
