from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core import db


@pytest.fixture()
def database(tmp_path) -> Iterator[None]:
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
