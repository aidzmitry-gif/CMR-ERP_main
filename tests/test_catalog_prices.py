"""Synthetic source prices: no live source, business names, credentials or stock writes."""
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, update
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
from core.services.native_catalog_import import (
    NOMENCLATURE,
    SourceRow,
    SourceUnitBinding,
    bind_source_units,
    digest,
    import_catalog,
)
from modules.integrations.catalog_prices import (
    ZERO,
    CatalogPriceError,
    PricePacket,
    decode_packet,
    import_prices,
    read_reference_prices,
)
from modules.integrations.models import CatalogPriceObservation, CatalogPriceSnapshot, StockItem


def guid(number):
    return f"00000000-0000-0000-0000-{number:012x}"


def price_row(number=1, amount=Decimal("12.50"), **changes):
    return {"Номенклатура_Key": guid(number), "Характеристика_Key": ZERO,
            "ВидЦены_Key": guid(1001), "Упаковка_Key": ZERO, "Валюта_Key": guid(1002),
            "Period": "2026-07-01T10:00:00", "Цена": amount, **changes}


def packet(rows=None, **changes):
    rows = [price_row()] if rows is None else rows
    # Preserve decimal JSON tokens rather than converting through binary floats.
    prices = json.dumps({"value": rows}, ensure_ascii=False, default=lambda _: "DECIMAL_TOKEN")
    for row in rows:
        if isinstance(row.get("Цена"), Decimal):
            prices = prices.replace('"DECIMAL_TOKEN"', str(row["Цена"]), 1)
    kinds = json.dumps({"value": [{"Ref_Key": guid(1001), "Description": "Synthetic wholesale",
        "DeletionMark": False, "IsFolder": False, "ИспользоватьПриПродаже": True,
        "ЦенаВключаетНДС": False, "ВалютаЦены_Key": guid(1002)}]}, ensure_ascii=False)
    currencies = json.dumps({"value": [{"Ref_Key": guid(1002), "Code": "933",
        "Description": "Synthetic currency", "DeletionMark": False}]})
    return replace(PricePacket(str(uuid4()), "test:prices", guid(1001),
        datetime(2026, 7, 2), datetime(2026, 7, 2, tzinfo=UTC), prices, kinds, currencies,
        digest(prices), digest(kinds), digest(currencies)), **changes)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:").execution_options(
        schema_translate_map={"integrations": None})
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine, tables=[Counterparty.__table__, CounterpartyAlias.__table__,
        NomenclatureCategory.__table__, Sku.__table__, CatalogSourceIdentity.__table__,
        CatalogSourceRevision.__table__, CatalogPriceSnapshot.__table__,
        CatalogPriceObservation.__table__, StockItem.__table__])
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed(db, number=1, *, bind=True):
    raw = json.dumps({"Ref_Key": guid(number), "DataVersion": "v1", "Code": "same-source-code",
        "Description": "Synthetic product", "DeletionMark": False, "IsFolder": False,
        "Parent_Key": None, "ЕдиницаИзмерения_Key": guid(99)}, ensure_ascii=False)
    source = SourceRow(NOMENCLATURE, raw)
    import_catalog(db, "test:prices", [source], actor="synthetic-test")
    db.commit()
    identity = db.scalar(select(CatalogSourceIdentity).where(
        CatalogSourceIdentity.source_guid == guid(number)))
    if bind:
        unit = json.dumps({"Ref_Key": guid(99), "DataVersion": "u1", "Description": "unit",
                           "DeletionMark": False}, ensure_ascii=False)
        bind_source_units(db, "test:prices", [SourceUnitBinding(source, unit,
            identity.revision_no, identity.target_sha, "a" * 64)],
            actor="synthetic-test", activate=True)
        db.commit()
    return db.get(Sku, identity.sku_id)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_decode_preserves_zero_dimensions_currency_and_vat():
    selected, rows, _ = decode_packet(packet([price_row(amount=Decimal("0.00"))]))
    assert selected["ЦенаВключаетНДС"] is False
    assert rows[0]["price_text"] == "0.00" and rows[0]["price"] == 0
    assert rows[0]["currency_code"] == "933" and rows[0]["package_guid"] == ZERO


@pytest.mark.parametrize("changes,reason", [
    ({"Цена": True}, "PRICE_TYPE"),
    ({"Цена": "12.50"}, "PRICE_TYPE"),
    ({"Цена": Decimal("-1")}, "PRICE_PRECISION"),
    ({"Цена": Decimal("1e18")}, "PRICE_PRECISION"),
    ({"Цена": Decimal("0.00000000001")}, "PRICE_PRECISION"),
    ({"Цена": Decimal("NaN")}, "NONFINITE_JSON"),
    ({"Цена": Decimal("Infinity")}, "NONFINITE_JSON"),
    ({"Period": "2026-07-03T00:00:00"}, "PRICE_DATE"),
    ({"Period": "2026-07-01T00:00:00+03:00"}, "PRICE_DATE"),
    ({"Period": "2026-07-01T00:00:00.0000001"}, "PRICE_DATE"),
    ({"Номенклатура_Key": ZERO}, "GUID"),
    ({"ВидЦены_Key": guid(1003)}, "PRICE_KIND"),
])
def test_invalid_price_packet_refused_before_any_write(db, changes, reason):
    with pytest.raises(CatalogPriceError, match=reason):
        import_prices(db, packet([price_row(**changes)]))
    assert count(db, CatalogPriceSnapshot) == count(db, CatalogPriceObservation) == 0


def test_hash_duplicate_json_and_dimensions_are_not_silently_accepted(db):
    p = packet()
    with pytest.raises(CatalogPriceError, match="SOURCE_HASH"):
        import_prices(db, replace(p, prices_sha="0" * 64))
    bad = '{"value": [], "value": []}'
    with pytest.raises(CatalogPriceError, match="DUPLICATE_JSON_KEY"):
        import_prices(db, replace(p, prices_text=bad, prices_sha=digest(bad)))
    with pytest.raises(CatalogPriceError, match="DUPLICATE_DIMENSIONS"):
        import_prices(db, packet([price_row(), price_row()]))
    assert count(db, CatalogPriceSnapshot) == 0


def test_capacity_and_partial_response_boundaries():
    rows = [price_row(i + 1) for i in range(10000)]
    assert len(decode_packet(packet(rows))[1]) == 10000
    with pytest.raises(CatalogPriceError, match="PARTIAL_SOURCE"):
        decode_packet(packet(rows + [price_row(10001)]))
    p = packet()
    raw = p.prices_text[:-1] + ', "odata.nextLink": "https://synthetic.invalid/next"}'
    with pytest.raises(CatalogPriceError, match="PARTIAL_SOURCE"):
        decode_packet(replace(p, prices_text=raw, prices_sha=digest(raw)))


def test_atomic_import_retains_mapped_held_unmapped_without_stock_writes(db):
    sku = seed(db)
    seed(db, 2, bind=False)
    db.add(StockItem(sku_code=sku.code, warehouse="synthetic-stock", qty_available=8,
                     qty_reserved=2, qty_forecast=3, price=999))
    db.commit()
    result = import_prices(db, packet([price_row(1), price_row(2), price_row(3)]))
    db.commit()
    assert (result["mapped"], result["held"], result["unmapped"], result["rows"]) == (1, 1, 1, 3)
    assert count(db, Sku) == 2 and count(db, CatalogPriceObservation) == 3
    stock = db.scalar(select(StockItem))
    assert (stock.qty_available, stock.qty_reserved, stock.qty_forecast, stock.price) == (8, 2, 3, 999)
    view = read_reference_prices(db)
    assert len(view["rows"]) == 1 and view["rows"][0]["sku_id"] == sku.id
    assert view["rows"][0]["price"] == "12.50"
    assert view["rows"][0]["application_status"] == "reference_only"
    assert "cost" not in view["rows"][0] and not view["snapshot"]["activity_verified"]


def test_replay_conflict_and_old_replay_do_not_switch_current(db):
    seed(db)
    first = packet()
    result = import_prices(db, first)
    db.commit()
    assert import_prices(db, first)["replayed"] is True
    db.commit()
    second = packet([price_row(amount=Decimal("20.00"))])
    import_prices(db, second)
    db.commit()
    assert import_prices(db, first)["is_current"] is False
    db.commit()
    different = replace(second, request_key=first.request_key)
    with pytest.raises(CatalogPriceError, match="REQUEST_CONFLICT"):
        import_prices(db, different)
    assert read_reference_prices(db)["snapshot"]["id"] == second.request_key
    assert count(db, CatalogPriceSnapshot) == 2 and count(db, CatalogPriceObservation) == 2
    assert result["snapshot_id"] == first.request_key


def test_failure_after_first_insert_rolls_back_entire_new_snapshot(db):
    seed(db)
    old = packet()
    import_prices(db, old)
    db.commit()

    def fail(*_):
        raise RuntimeError("synthetic-failure")

    event.listen(CatalogPriceObservation, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="synthetic-failure"):
            import_prices(db, packet())
    finally:
        event.remove(CatalogPriceObservation, "before_insert", fail)
    assert count(db, CatalogPriceSnapshot) == count(db, CatalogPriceObservation) == 1
    assert read_reference_prices(db)["snapshot"]["id"] == old.request_key


@pytest.mark.parametrize("tamper", ["native", "revision", "identity"])
def test_reader_withholds_price_after_catalog_mapping_changes(db, tamper):
    sku = seed(db)
    import_prices(db, packet())
    db.commit()
    if tamper == "native":
        sku.unit = "other-unit"
    elif tamper == "revision":
        db.scalar(select(CatalogSourceRevision).order_by(
            CatalogSourceRevision.revision_no.desc())).source_text += " "
    else:
        db.scalar(select(CatalogSourceIdentity)).holds = ["REVIEW_REQUIRED"]
    db.commit()
    view = read_reference_prices(db)
    assert view["rows"] == [] and view["snapshot"]["held"] == 1
    assert count(db, CatalogPriceObservation) == 1 and not db.dirty and not db.new


def test_unknown_currency_never_inherits_kind_currency(db):
    seed(db)
    import_prices(db, packet([price_row(Валюта_Key=ZERO)]))
    db.commit()
    row = db.scalar(select(CatalogPriceObservation))
    assert row.currency_code is None and row.mapping_reason == "CURRENCY_UNKNOWN"
    assert read_reference_prices(db)["rows"] == []


def test_zero_price_remains_reference_not_a_free_sale(db):
    seed(db)
    import_prices(db, packet([price_row(amount=Decimal("0.00"))]))
    db.commit()
    view = read_reference_prices(db)
    assert view["rows"][0]["price"] == "0.00"
    assert view["rows"][0]["application_status"] == "reference_only"
    assert view["rows"][0]["package_guid"] == ZERO


@pytest.mark.parametrize("tamper", ["price", "count", "raw"])
def test_corrupt_stored_prices_fail_closed_on_read_and_replay(db, tamper):
    seed(db)
    p = packet()
    import_prices(db, p)
    db.commit()
    if tamper == "price":
        db.execute(update(CatalogPriceObservation).values(price_text="99.00"))
    elif tamper == "count":
        db.execute(update(CatalogPriceSnapshot).values(row_count=2))
    else:
        db.execute(update(CatalogPriceSnapshot).values(prices_text="{}"))
    db.commit()
    with pytest.raises(CatalogPriceError):
        read_reference_prices(db)
    with pytest.raises(CatalogPriceError):
        import_prices(db, p)


def test_unconfigured_read_is_unknown_and_does_not_create_rows(db):
    assert read_reference_prices(db) == {"status": "unavailable", "snapshot": None, "rows": []}
    assert count(db, CatalogPriceSnapshot) == count(db, CatalogPriceObservation) == 0


def test_explicit_namespace_never_falls_back_to_matching_code_or_name(db):
    seed(db)
    import_prices(db, replace(packet(), namespace="other:source"))
    db.commit()
    assert read_reference_prices(db)["rows"] == []
    assert db.scalar(select(CatalogPriceObservation)).mapping_status == "unmapped"


def test_read_refresh_does_not_overwrite_or_autoflush_caller_edits(db):
    sku = seed(db)
    import_prices(db, packet())
    db.commit()
    sku.unit = "pending-caller-edit"
    with pytest.raises(CatalogPriceError, match="CLEAN_SESSION_REQUIRED"):
        read_reference_prices(db)
    assert sku.unit == "pending-caller-edit" and db.is_modified(sku)
    db.rollback()
    assert len(read_reference_prices(db)["rows"]) == 1
