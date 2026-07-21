from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).parents[1]


def test_migrations_build_the_same_schema_as_the_models(tmp_path, monkeypatch):
    """Fails when a model changes without a migration (run `alembic revision --autogenerate`)."""
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.check(cfg)  # raises if autogenerate would produce operations
    command.downgrade(cfg, "base")
