"""Conservative identity backfill and rollback, without changing original documents."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


@pytest.fixture
def migrated():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("ATTACH DATABASE ':memory:' AS sales"))
        connection.execute(text("CREATE TABLE counterparty (id INTEGER PRIMARY KEY, name TEXT, is_active BOOLEAN, merged_into_id INTEGER)"))
        connection.execute(text("CREATE TABLE sales.deal (id INTEGER PRIMARY KEY, counterparty TEXT)"))
        connection.execute(text("CREATE TABLE sales.deal_document (id INTEGER PRIMARY KEY, original TEXT)"))
        connection.execute(text("INSERT INTO sales.deal_document VALUES (1,'unchanged original hash')"))
        connection.execute(text("INSERT INTO counterparty VALUES (1,'Unique',true,NULL),(2,'Same',true,NULL),(3,'Same',true,NULL),(4,'Archived',false,NULL)"))
        connection.execute(text("INSERT INTO sales.deal VALUES (1,'Unique'),(2,'Same'),(3,'Archived'),(4,'Missing')"))
        path = Path(__file__).resolve().parents[1] / "migrations/versions/0118_sales_party_identity.py"
        spec = importlib.util.spec_from_file_location("migration_0118", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        yield connection, module
    engine.dispose()


def test_backfill_only_unique_active_identity_and_reverse(migrated):
    connection, module = migrated
    rows = connection.execute(text("SELECT id, counterparty_id, branch_id FROM sales.deal ORDER BY id")).all()
    assert [tuple(r) for r in rows] == [(1, 1, None), (2, None, None), (3, None, None), (4, None, None)]
    module.downgrade()
    assert connection.execute(text("SELECT original FROM sales.deal_document")).scalar() == "unchanged original hash"
    assert connection.execute(text("SELECT counterparty FROM sales.deal WHERE id=1")).scalar() == "Unique"


@pytest.mark.parametrize("change", [
    "UPDATE sales.deal SET branch_id=7 WHERE id=1",
    "UPDATE counterparty SET name='Renamed' WHERE id=1",
    "UPDATE sales.deal SET counterparty_id=2 WHERE id=2",
])
def test_refuse_loss_of_selected_or_renamed_identity(migrated, change):
    connection, module = migrated
    connection.execute(text(change))
    with pytest.raises(RuntimeError, match="discard party identity"):
        module.downgrade()
    assert connection.execute(text("SELECT original FROM sales.deal_document")).scalar() == "unchanged original hash"
