import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table, create_engine, inspect, text

from alembic import command

ROOT = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return config


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A throwaway database: a SQLite file, or a fresh schema when TEST_DATABASE_URL is set."""
    if not TEST_DATABASE_URL:
        url = f"sqlite:///{tmp_path / 'migrations.db'}"
        monkeypatch.setenv("DATABASE_URL", url)
        yield url
        return
    sync_url = TEST_DATABASE_URL.replace("+psycopg_async", "+psycopg")
    schema = f"m_{uuid4().hex}"
    admin = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = f"{sync_url}{'&' if '?' in sync_url else '?'}options=-csearch_path%3D{schema}"
    monkeypatch.setenv("DATABASE_URL", url)
    try:
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_migration_chain_has_exactly_one_head() -> None:
    assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1


def test_upgrade_downgrade_and_upgrade_again(database: str) -> None:
    config = alembic_config()

    command.upgrade(config, "head")
    assert "contacts" in table_names(database)
    command.downgrade(config, "base")
    assert table_names(database) == set()
    command.upgrade(config, "head")
    assert "tenant_feature_flags" in table_names(database)


def test_models_match_migrations(database: str) -> None:
    """Fails when a model changes without a new revision (tests build the schema with create_all,
    so nothing else would notice)."""
    config = alembic_config()
    command.upgrade(config, "head")

    command.check(config)


def test_revision_ids_fit_the_default_version_column() -> None:
    """alembic_version.version_num is VARCHAR(32) on Postgres; SQLite would not notice."""
    scripts = ScriptDirectory.from_config(alembic_config())

    too_long = [rev.revision for rev in scripts.walk_revisions() if len(rev.revision) > 32]

    assert too_long == []


def test_downgrade_truncates_long_transition_reasons_instead_of_failing(database: str) -> None:
    """0015 widened the column; rolling back with long reasons stored must not abort."""
    config = alembic_config()
    command.upgrade(config, "head")
    engine = create_engine(database)
    try:
        table = Table("workflow_transitions", MetaData(), autoload_with=engine)
        values: dict[str, object] = {}
        for column in table.columns:
            if column.nullable or column.server_default is not None:
                continue
            python_type = column.type.python_type
            if python_type is datetime:
                values[column.name] = datetime(2026, 1, 1, tzinfo=UTC)
            elif python_type in (dict, list):
                values[column.name] = python_type()
            else:
                values[column.name] = python_type() if python_type is not str else "x"
        values["reason"] = "r" * 2000
        with engine.begin() as connection:
            connection.execute(table.insert().values(**values))

        command.downgrade(config, "0014_phase10_feature_flags")

        with engine.connect() as connection:
            stored = connection.execute(text("SELECT reason FROM workflow_transitions")).scalar()
        assert stored == "r" * 500
    finally:
        engine.dispose()
