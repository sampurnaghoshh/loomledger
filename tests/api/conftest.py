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


def login(client: TestClient, email: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["token"]


@pytest.fixture(scope="session")
def owner_token(client) -> str:
    return login(client, "owner@everest.test")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
