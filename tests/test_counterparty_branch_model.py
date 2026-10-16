"""Additive identity storage and non-destructive local migration checks."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.domain.models import Counterparty, CounterpartyBranch, CounterpartyBranchAlias


@pytest.fixture
def engine():
    db = create_engine("sqlite://")
    @event.listens_for(db, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    yield db
    db.dispose()


def test_shared_unp_branches_preserve_parent_and_leading_zero(engine):
    Counterparty.__table__.create(engine)
    CounterpartyBranch.__table__.create(engine)
    with Session(engine) as session:
        parent = Counterparty(name="Legacy", unp="600187521", display_name="Short", legal_name="Legal")
        session.add(parent)
        session.flush()
        session.add_all([
            CounterpartyBranch(legal_entity_id=parent.id, name="Same name", tax_mode="shared", portal_branch_code="0001"),
            CounterpartyBranch(legal_entity_id=parent.id, name="Same name", tax_mode="shared", portal_branch_code="0002"),
        ])
        session.commit()
        branches = session.scalars(select(CounterpartyBranch).order_by(CounterpartyBranch.id)).all()
        assert [b.portal_branch_code for b in branches] == ["0001", "0002"]
        assert all(b.legal_entity_id == parent.id for b in branches)
        assert parent.name == "Legacy"
        assert (parent.display_name, parent.legal_name) == ("Short", "Legal")


@pytest.mark.parametrize("values", [
    {"legal_entity_id": 999},
    {"tax_mode": "guessed"},
    {"portal_branch_code": "001"},
])
def test_branch_database_guards(engine, values):
    Counterparty.__table__.create(engine)
    CounterpartyBranch.__table__.create(engine)
    with Session(engine) as session:
        parent = Counterparty(name="Parent")
        session.add(parent)
        session.commit()
        session.add(CounterpartyBranch(**{"legal_entity_id": parent.id, "name": "Branch", **values}))
        with pytest.raises(IntegrityError):
            session.commit()


def migration(connection):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0117_counterparty_names_branches.py"
    spec = importlib.util.spec_from_file_location("migration_0117", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    return module


def test_source_identity_cannot_be_assigned_to_two_branches(engine):
    Counterparty.__table__.create(engine)
    CounterpartyBranch.__table__.create(engine)
    CounterpartyBranchAlias.__table__.create(engine)
    with Session(engine) as session:
        parent = Counterparty(name="Parent")
        session.add(parent)
        session.flush()
        branches = [CounterpartyBranch(legal_entity_id=parent.id, name="Same") for _ in range(2)]
        session.add_all(branches)
        session.flush()
        session.add(CounterpartyBranchAlias(branch_id=branches[0].id, source="1c", external_ref="branch-ref"))
        session.commit()
        session.add(CounterpartyBranchAlias(branch_id=branches[1].id, source="1c", external_ref="branch-ref"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_migration_preserves_names_and_reverses_unused_schema(engine):
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE counterparty (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL)"))
        connection.execute(text("INSERT INTO counterparty VALUES (7, 'Original legal name')"))
        change = migration(connection)
        change.upgrade()
        row = connection.execute(text("SELECT name, display_name, legal_name FROM counterparty")).one()
        assert tuple(row) == ("Original legal name", "Original legal name", None)
        change.downgrade()
        assert connection.execute(text("SELECT name FROM counterparty WHERE id=7")).scalar() == "Original legal name"
        change.upgrade()


@pytest.mark.parametrize("modification", [
    "UPDATE counterparty SET display_name='User short name'",
    "UPDATE counterparty SET legal_name=name",
    "INSERT INTO counterparty_branch (legal_entity_id,name) VALUES (7,'Branch')",
])
def test_downgrade_refuses_to_lose_new_data(engine, modification):
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE counterparty (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL)"))
        connection.execute(text("INSERT INTO counterparty VALUES (7, 'Original')"))
        change = migration(connection)
        change.upgrade()
        connection.execute(text(modification))
        with pytest.raises(RuntimeError, match="discard"):
            change.downgrade()
        assert connection.execute(text("SELECT name FROM counterparty WHERE id=7")).scalar() == "Original"
