"""Opt-in synthetic PostgreSQL proof; never connect to the application database."""
import importlib.util
import os
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.base import Base
from core.domain.models import (
    CatalogSourceIdentity,
    CatalogSourceRevision,
    Counterparty,
    CounterpartyAlias,
    Sku,
)
from core.domain.reference import NomenclatureCategory
from modules.integrations.catalog_prices import (
    CatalogPriceError,
    import_prices,
    read_reference_prices,
)
from modules.integrations.models import CatalogPriceObservation, CatalogPriceSnapshot, StockItem
from tests.test_catalog_prices import count, packet, price_row, seed

URL = os.getenv("CATALOG_PRICE_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="isolated synthetic PostgreSQL not configured")
TABLES = [Counterparty.__table__, CounterpartyAlias.__table__, NomenclatureCategory.__table__,
          Sku.__table__, CatalogSourceIdentity.__table__, CatalogSourceRevision.__table__, StockItem.__table__]
NEW_TABLES = {"catalog_price_snapshot", "catalog_price_observation"}


def migration():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0199_catalog_price_snapshots.py"
    spec = importlib.util.spec_from_file_location("catalog_prices_0199", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migrate(connection, direction):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration(), direction)()


@pytest.fixture
def pg():
    url = make_url(URL)
    # This opt-in variable must point to the dedicated disposable local container.
    assert url.host == "127.0.0.1" and url.database == "g13p_synthetic"
    assert url.username == "postgres" and url.port is not None
    name = "g13p_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine = create_engine(url.set(database=name), connect_args={
        "options": "-c statement_timeout=10000 -c lock_timeout=5000"})
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE SCHEMA integrations")
            Base.metadata.create_all(connection, tables=TABLES)
            migrate(connection, "upgrade")
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}"')
        admin.dispose()


def test_migration_matches_models_and_empty_downgrade_is_additive(pg):
    def only_prices(obj, name, kind, reflected, compared):
        table = obj if kind == "table" else getattr(obj, "table", None)
        return table is not None and table.name in NEW_TABLES

    with pg.begin() as connection:
        context = MigrationContext.configure(connection, opts={"include_schemas": True,
            "include_object": only_prices, "compare_type": True, "compare_server_default": True})
        assert compare_metadata(context, Base.metadata) == []
        before = set(inspect(connection).get_table_names(schema="public"))
        migrate(connection, "downgrade")
        assert set(inspect(connection).get_table_names(schema="public")) == before
        assert not NEW_TABLES.intersection(inspect(connection).get_table_names(schema="integrations"))
        migrate(connection, "upgrade")
        assert NEW_TABLES.issubset(inspect(connection).get_table_names(schema="integrations"))


def test_native_decimal_boundary_and_readback_are_exact(pg):
    value = Decimal("999999999999999999.1234567890")
    with Session(pg) as db:
        seed(db)
        import_prices(db, packet([price_row(amount=value)]))
        db.commit()
        assert db.scalar(select(CatalogPriceObservation.price)) == value
        view = read_reference_prices(db)
        assert view["rows"][0]["price"] == str(value)
        assert view["rows"][0]["application_status"] == "reference_only"


def test_native_capacity_preserves_all_ten_thousand_rows(pg):
    with Session(pg) as db:
        result = import_prices(db, packet([price_row(i + 1) for i in range(10000)]))
        db.commit()
        assert result["rows"] == result["unmapped"] == count(db, CatalogPriceObservation) == 10000
        assert count(db, Sku) == count(db, StockItem) == 0
        assert read_reference_prices(db)["snapshot"]["unmapped"] == 10000


@pytest.mark.parametrize("same_request", [False, True])
def test_concurrent_imports_serialize_without_partial_or_duplicate_snapshots(pg, same_request):
    with Session(pg) as db:
        seed(db)
    first = packet()
    inputs = [first, first if same_request else packet([price_row(amount=Decimal("15.00"))])]
    barrier = Barrier(2, timeout=10)

    def load(p):
        with Session(pg) as db:
            barrier.wait()
            result = import_prices(db, p)
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(load, p) for p in inputs]
        results = [future.result(timeout=20) for future in futures]
    with Session(pg) as db:
        assert count(db, CatalogPriceSnapshot) == count(db, CatalogPriceObservation) == (1 if same_request else 2)
        assert len(list(db.scalars(select(CatalogPriceSnapshot).where(CatalogPriceSnapshot.is_current)))) == 1
        assert len(read_reference_prices(db)["rows"]) == 1
    assert sum(result["replayed"] for result in results) == int(same_request)


def test_failure_during_current_switch_keeps_old_snapshot_current(pg):
    with Session(pg) as db:
        seed(db)
        old = packet()
        import_prices(db, old)
        db.commit()

        def fail_on_activation(mapper, connection, target):
            if target.is_current and target.id != old.request_key:
                raise RuntimeError("synthetic-switch-failure")

        event.listen(CatalogPriceSnapshot, "before_update", fail_on_activation)
        try:
            with pytest.raises(RuntimeError, match="synthetic-switch-failure"):
                import_prices(db, packet())
        finally:
            event.remove(CatalogPriceSnapshot, "before_update", fail_on_activation)
        db.commit()
        assert count(db, CatalogPriceSnapshot) == count(db, CatalogPriceObservation) == 1
        assert read_reference_prices(db)["snapshot"]["id"] == old.request_key


def test_downgrade_with_retained_history_refuses_before_ddl(pg):
    with Session(pg) as db:
        import_prices(db, packet())
        db.commit()
    with pg.begin() as connection:
        with pytest.raises(RuntimeError, match="Cannot remove retained"):
            migrate(connection, "downgrade")
        assert NEW_TABLES.issubset(inspect(connection).get_table_names(schema="integrations"))
        assert connection.scalar(text("SELECT count(*) FROM integrations.catalog_price_snapshot")) == 1
        assert connection.scalar(text("SELECT count(*) FROM integrations.catalog_price_observation")) == 1


@pytest.mark.parametrize("changes", [
    {"price": Decimal("-1")},
    {"identity_revision": None},
    {"sku_id": 999999999},
])
def test_database_constraints_reject_invalid_amount_or_native_binding(pg, changes):
    with Session(pg) as db:
        seed(db)
        import_prices(db, packet())
        db.commit()
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(update(CatalogPriceObservation).values(**changes))
        assert len(read_reference_prices(db)["rows"]) == 1


@pytest.mark.parametrize("tamper", ["sku", "identity", "revision", "observation", "snapshot"])
def test_commits_from_other_session_are_not_hidden_by_identity_map(pg, tamper):
    with Session(pg, expire_on_commit=False) as first:
        seed(first)
        p = packet()
        import_prices(first, p)
        first.commit()
        # Keep strong references: SQLAlchemy otherwise may discard identity-map entries.
        cached = [first.scalar(select(model)) for model in (
            Sku, CatalogSourceIdentity, CatalogPriceSnapshot, CatalogPriceObservation)]
        cached.append(first.scalar(select(CatalogSourceRevision).order_by(
            CatalogSourceRevision.revision_no.desc()).limit(1)))
        with Session(pg) as second:
            if tamper == "sku":
                second.execute(update(Sku).values(unit="other-unit"))
            elif tamper == "identity":
                second.execute(update(CatalogSourceIdentity).values(holds=["REVIEW_REQUIRED"]))
            elif tamper == "revision":
                second.execute(update(CatalogSourceRevision).values(source_text="{}"))
            elif tamper == "observation":
                second.execute(update(CatalogPriceObservation).values(price_text="99.00"))
            else:
                second.execute(update(CatalogPriceSnapshot).values(row_count=2))
            second.commit()
        assert len(cached) == 5
        if tamper in ("observation", "snapshot"):
            with pytest.raises(CatalogPriceError):
                read_reference_prices(first)
            with pytest.raises(CatalogPriceError):
                import_prices(first, p)
        else:
            assert read_reference_prices(first)["rows"] == []


def test_overlapping_import_and_downgrade_cannot_erase_committed_history(pg):
    started = Event()
    worker_pid = []
    statements = []

    def downgrade():
        with pg.begin() as connection:
            worker_pid.append(connection.scalar(text("SELECT pg_backend_pid()")))
            event.listen(connection, "before_cursor_execute", lambda conn, cursor, sql, *args:
                         statements.append(sql))
            started.set()
            with pytest.raises(RuntimeError, match="Cannot remove retained"):
                migrate(connection, "downgrade")

    with Session(pg) as importer, ThreadPoolExecutor(max_workers=1) as executor:
        import_prices(importer, packet())  # Row exists but is not committed yet.
        future = executor.submit(downgrade)
        try:
            assert started.wait(timeout=5)
            blocked = False
            with pg.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid))"),
                                       {"pid": worker_pid[0]}):
                        blocked = True
                        break
                    time.sleep(0.01)
            assert blocked, "downgrade must wait for the importing transaction"
            importer.commit()
            future.result(timeout=10)
        finally:
            importer.rollback()
        assert statements[0].startswith("LOCK TABLE")
        assert count(importer, CatalogPriceSnapshot) == count(importer, CatalogPriceObservation) == 1
