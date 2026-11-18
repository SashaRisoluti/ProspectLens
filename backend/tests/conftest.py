import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from prospectlens.config import SportConfig, load_sport
from prospectlens.providers.base import SeasonBundle
from prospectlens.providers.mock import MockProvider

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
TEST_DB = os.environ.get("TEST_DATABASE_URL")
if TEST_DB:
    os.environ["DATABASE_URL"] = TEST_DB


@pytest.fixture(scope="session")
def cfg() -> SportConfig:
    return load_sport(CONFIG_DIR)


@pytest.fixture(scope="session")
def tiny_bundles(cfg: SportConfig) -> list[SeasonBundle]:
    return list(MockProvider(cfg, "tiny", seed=7).bundles())


@pytest.fixture
def db() -> Iterator[Session]:
    """Database di test vuoto, schema creato con le migrazioni Alembic."""
    if not TEST_DB:
        pytest.skip("TEST_DATABASE_URL non impostata (usa `make test`)")
    from alembic import command
    from alembic.config import Config

    engine = create_engine(TEST_DB)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    with Session(engine) as session:
        yield session
    engine.dispose()
