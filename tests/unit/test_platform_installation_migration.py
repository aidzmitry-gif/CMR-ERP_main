"""Exercise the additive migration and prevent silent removal of a saved choice."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def migration(connection):
    path = Path(__file__).parents[2] / "migrations/versions/0204_platform_installation.py"
    spec = importlib.util.spec_from_file_location("platform_installation_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    assert module.revision == "0204" and module.down_revision == "0203"
    return module


def test_empty_installation_migration_roundtrip():
    with create_engine("sqlite:///:memory:").begin() as connection:
        module = migration(connection)
        module.upgrade()
        assert "platform_installation" in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT count(*) FROM platform_installation")).scalar_one() == 0
        module.downgrade()
        assert "platform_installation" not in inspect(connection).get_table_names()


def test_downgrade_preserves_an_explicit_platform_choice():
    with create_engine("sqlite:///:memory:").begin() as connection:
        module = migration(connection)
        module.upgrade()
        connection.execute(text("""INSERT INTO platform_installation
            (id, revision, organization_id, organization_unp, request_id, command_digest, actor)
            VALUES (1, 1, 7, '987654321', 'synthetic', 'synthetic', 'synthetic')"""))
        with pytest.raises(RuntimeError, match="preserved"):
            module.downgrade()
        assert connection.execute(text("SELECT organization_id FROM platform_installation")).scalar_one() == 7
