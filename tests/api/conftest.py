"""API test fixtures: the real app (lifespan, pool, middleware) against a freshly seeded test database.

Uses TEST_DATABASE_URL (default loomledger_test) rather than the demo DB, so rehearsals
(e.g. an applied recall) never change what the API tests see.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.auth import require_role
from tests.conftest import TEST_URL, _fresh

MOCKS = Path(__file__).resolve().parents[2] / "docs" / "api-mocks"
PASSWORD = "demo1234"   # seeded for every demo user (seed/seed.py)


def load_mock(name: str) -> dict:
    return json.loads((MOCKS / f"{name}.json").read_text(encoding="utf-8"))


class _Probe(BaseModel):
    kg: float = Field(gt=0)
    lot_code: str = Field(pattern=r"^Y-\d{3,}$")


def _add_test_routes(app: FastAPI) -> None:
    """Tiny routes that exist only in tests, to exercise platform pieces without feature modules."""

    @app.get("/api/_test/qc-only")
    def qc_only(user: dict = Depends(require_role("qc"))):
        return {"role": user["role"]}

    @app.post("/api/_test/validate")
    def validate(body: _Probe):
        return body.model_dump()

    @app.get("/api/_test/boom")
    def boom():
        raise RuntimeError("SELECT password_hash FROM app_user -- must never reach the client")


@pytest.fixture(scope="session")
def app(monkeypatch_session) -> FastAPI:
    conn = _fresh()
    conn.close()
    monkeypatch_session.setenv("DATABASE_URL", TEST_URL)
    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    application = create_app()
    _add_test_routes(application)
    return application


@pytest.fixture(scope="session")
def monkeypatch_session():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()
    from app.config import get_settings
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def client(app: FastAPI):
    with TestClient(app, raise_server_exceptions=False) as c:   # `with` runs the lifespan (opens the pool)
        yield c


def assert_same_shape(actual, mock, path: str = "$") -> None:
    """Contract check: same keys and JSON types, recursively. int/float are both "number";
    a null on either side matches anything (nullable field). Every list element is checked
    against the mock's first element."""
    if actual is None or mock is None:
        return
    if isinstance(mock, bool) or isinstance(actual, bool):
        assert type(actual) is type(mock), f"{path}: {type(actual).__name__} != {type(mock).__name__}"
    elif isinstance(mock, (int, float)):
        assert isinstance(actual, (int, float)), f"{path}: expected number, got {type(actual).__name__}"
    elif isinstance(mock, dict):
        assert isinstance(actual, dict), f"{path}: expected object"
        assert set(actual) == set(mock), f"{path}: keys differ: +{set(actual) - set(mock)} -{set(mock) - set(actual)}"
        for k in mock:
            assert_same_shape(actual[k], mock[k], f"{path}.{k}")
    elif isinstance(mock, list):
        assert isinstance(actual, list), f"{path}: expected array"
        if mock:
            for i, item in enumerate(actual):
                assert_same_shape(item, mock[0], f"{path}[{i}]")
    else:
        assert type(actual) is type(mock), f"{path}: {type(actual).__name__} != {type(mock).__name__}"


def apply_story_recall() -> None:
    """Apply the Y-112 recall on the test DB and pin its time to the story clock, exactly as
    scripts/export_mocks.py does, so the *_after mocks can be compared value for value."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import psycopg

    from seed import scenario as S
    recall_at = datetime.combine(S.ANCHOR_DATE, S.RECALL_APPLIED_AT, ZoneInfo(S.TIMEZONE))
    with psycopg.connect(TEST_URL) as conn, conn.transaction():
        y112 = conn.execute("SELECT id FROM lot WHERE code = %s", (S.Y112,)).fetchone()[0]
        conn.execute("SELECT apply_recall(%s, 'Colour mismatch traced to yarn lot Y-112', "
                     "(SELECT id FROM app_user WHERE role = 'qc'))", (y112,))
        conn.execute("""UPDATE order_event SET created_at = %s
                         WHERE created_at = (SELECT initiated_at FROM recall WHERE root_lot_id = %s)""",
                     (recall_at, y112))
        conn.execute("UPDATE recall SET initiated_at = %s WHERE root_lot_id = %s", (recall_at, y112))


@pytest.fixture(scope="module")
def reseed_after_module(app):
    """For modules whose tests write: the ledger is append-only, so restore by reseeding when the module ends.
    Put read/contract tests first in the module — they run before any write."""
    yield
    _fresh().close()


@pytest.fixture(scope="module")
def live_server(app):
    """A real uvicorn server in a thread (real sockets, real lifespan) on the test DB: (app, base_url)."""
    import socket
    import threading
    import time

    import uvicorn

    from app.main import create_app

    def wait_until(cond, timeout: float, what: str) -> None:
        deadline = time.monotonic() + timeout
        while not cond():
            if time.monotonic() > deadline:
                raise AssertionError(f"timed out waiting for {what}")
            time.sleep(0.02)

    server_app = create_app()       # own instance: its own pool, listener and broadcaster
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(server_app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_until(lambda: server.started, 10, "uvicorn to start")
    wait_until(server_app.state.floor_listener.connected.is_set, 5, "LISTEN")
    wait_until(server_app.state.alerts_listener.connected.is_set, 5, "LISTEN alerts")
    yield server_app, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
    assert not thread.is_alive(), "server (and floor listener) did not shut down"


def login(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["token"]


@pytest.fixture(scope="session")
def owner_token(client) -> str:
    return login(client, "owner@everest.test")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
