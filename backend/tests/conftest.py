from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core import db


@pytest.fixture()
def database(tmp_path, monkeypatch) -> Iterator[None]:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_dir", tmp_path / "documents")
    # AB_TEST_DATABASE_URL runs the suite against another database, e.g. PostgreSQL in CI.
    url = os.environ.get("AB_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    db.configure(url)
    from app import models  # noqa: F401  (register mappers)

    db.Base.metadata.drop_all(db.engine())
    db.Base.metadata.create_all(db.engine())
    yield
    db.engine().dispose()


@pytest.fixture()
def client(database) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_simulated_receiver():
    from app.integrations import exchange

    exchange.receiver = exchange.SimulatedReceiver()
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from app.core.ratelimit import limiter

    limiter.reset()
    yield
