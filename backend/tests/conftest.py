from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core import db


@pytest.fixture()
def database(tmp_path, monkeypatch) -> Iterator[None]:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_dir", tmp_path / "documents")
    db.configure(f"sqlite:///{tmp_path / 'test.db'}")
    from app import models  # noqa: F401  (register mappers)

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
