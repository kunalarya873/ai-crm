from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from alembic import command

ROOT = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return config


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


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
        with engine.begin() as connection:
            columns = [
                column
                for column in inspect(connection).get_columns("workflow_transitions")
                if not column["nullable"] and column["default"] is None
            ]
            values: dict[str, object] = {}
            for column in columns:
                kind = str(column["type"]).upper()
                if "INT" in kind or "BOOL" in kind:
                    values[column["name"]] = 1
                elif "DATE" in kind or "TIME" in kind:
                    values[column["name"]] = "2026-01-01 00:00:00"
                elif "JSON" in kind:
                    values[column["name"]] = "{}"
                else:
                    values[column["name"]] = "x"
            values["reason"] = "r" * 2000
            names = ", ".join(values)
            marks = ", ".join(f":{name}" for name in values)
            connection.execute(
                text(f"INSERT INTO workflow_transitions ({names}) VALUES ({marks})"), values
            )

        command.downgrade(config, "0014_phase10_feature_flags")

        with engine.connect() as connection:
            stored = connection.execute(text("SELECT reason FROM workflow_transitions")).scalar()
        assert stored == "r" * 500
    finally:
        engine.dispose()
