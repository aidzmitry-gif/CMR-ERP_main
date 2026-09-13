"""Canonical command helpers only; full order-package acceptance is separate."""
import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting.models import Organization
from modules.procurement.models import PurchaseOrder, PurchaseOrderLine, PurchaseRequest
from modules.procurement.ownership import PurchaseOwnership
from tests.accounting.test_postgres import pg_factory  # noqa: F401


async def test_order_command_canonical_json_matches_python(pg_factory):  # noqa: F811
    sql = (Path(__file__).resolve().parents[2] / "modules/procurement/order_creation_guards.sql").read_text(encoding="utf-8")
    helpers = "CREATE OR REPLACE FUNCTION procurement.order_command_json" + sql.split(
        "CREATE OR REPLACE FUNCTION procurement.order_command_json", 1)[1].split(
        "-- Immutable evidence of the actual pre-transition state", 1)[0]
    async with pg_factory() as session:
        connection = await session.connection()
        await connection.exec_driver_sql(helpers)
        for supplier in ['Поставщик "quote" \\ tab\tline\n🙂', "漢字\u2028", "control\b\r"]:
            for basis in [None, {"request_id": 2147483647, "expected_stage": "approval",
                                 "expected_hash": "a" * 64, "link_evidence": supplier}]:
                command = {"request_key": "11111111-1111-4111-8111-111111111111",
                           "document": {"supplier": supplier, "eta_date": None, "freight_byn": "0.00",
                               "lines": [{"sku_code": "SKU", "qty": "1.00", "goods_value_byn": "999999999999.99",
                                          "weight": "0.001", "volume": "0.0001"}]},
                           "ownership_evidence": supplier, "request_basis": basis}
                expected = json.dumps(command, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                actual = await session.scalar(text("SELECT procurement.order_command_json(CAST(:value AS jsonb))"), {"value": expected})
                assert actual == expected
        for n in range(0x110000):
            if not chr(n).isspace():
                continue
            value = json.dumps(chr(n) + "SKU" + chr(n))
            assert await session.scalar(text("SELECT procurement.order_command_text(CAST(:value AS jsonb),64)"), {"value": value}) is False
        assert await session.scalar(text("SELECT procurement.order_command_text(NULL,64)")) is False
        assert await session.scalar(text("SELECT procurement.order_command_text('\"SKU\"'::jsonb,64)")) is True


async def test_order_insert_proof_rejects_updates_and_handles_savepoints(pg_factory):  # noqa: F811
    sql = (Path(__file__).resolve().parents[2] / "modules/procurement/order_creation_guards.sql").read_text(encoding="utf-8")
    provenance = sql.split("CREATE OR REPLACE FUNCTION procurement.order_command_json", 1)[0]
    async with pg_factory() as session:
        connection = await session.connection()
        await connection.run_sync(lambda c: PurchaseOrder.__table__.create(c, checkfirst=True))
        await connection.run_sync(lambda c: PurchaseOrderLine.__table__.create(c, checkfirst=True))
        old = await session.scalar(text("INSERT INTO procurement.purchase_order DEFAULT VALUES RETURNING id"))
        if not await session.scalar(text("SELECT to_regclass('procurement.order_insert_proof')")):
            await connection.exec_driver_sql(provenance)
        await session.commit()
        old_line = await session.scalar(text("INSERT INTO procurement.purchase_order_line(order_id,sku_code) VALUES (:id,'SKU') RETURNING id"), {"id": old})
        await session.execute(text("UPDATE procurement.purchase_order SET number=number WHERE id=:id"), {"id": old})
        assert not await session.scalar(text("SELECT EXISTS(SELECT 1 FROM procurement.order_insert_proof WHERE order_id=:id AND root_transaction=txid_current())"), {"id": old})
        with pytest.raises(DBAPIError, match="must originate"):
            async with session.begin_nested():
                await session.execute(text("INSERT INTO procurement.order_insert_proof VALUES (:id,txid_current())"), {"id": old})
        async with session.begin_nested():
            new = await session.scalar(text("INSERT INTO procurement.purchase_order DEFAULT VALUES RETURNING id"))
            assert await session.scalar(text("SELECT root_transaction=txid_current() FROM procurement.order_insert_proof WHERE order_id=:id"), {"id": new})
        with pytest.raises(DBAPIError, match="parent is immutable"):
            async with session.begin_nested():
                await session.execute(text("UPDATE procurement.purchase_order_line SET order_id=:new WHERE id=:line"), {"new": new, "line": old_line})
        for statement in ("UPDATE procurement.order_insert_proof SET root_transaction=txid_current()",
                          "DELETE FROM procurement.order_insert_proof", "TRUNCATE procurement.order_insert_proof"):
            with pytest.raises(DBAPIError, match="immutable"):
                async with session.begin_nested():
                    await session.execute(text(statement))
        savepoint = await session.begin_nested()
        rolled_back = await session.scalar(text("INSERT INTO procurement.purchase_order DEFAULT VALUES RETURNING id"))
        await savepoint.rollback()
        assert not await session.scalar(text("SELECT EXISTS(SELECT 1 FROM procurement.order_insert_proof WHERE order_id=:id)"), {"id": rolled_back})
        await session.execute(text("DELETE FROM procurement.purchase_order WHERE id=:id"), {"id": new})
        assert await session.scalar(text("SELECT EXISTS(SELECT 1 FROM procurement.order_insert_proof WHERE order_id=:id)"), {"id": new})


async def test_approval_transition_proof_records_old_state_and_root_transaction(pg_factory):  # noqa: F811
    sql = (Path(__file__).resolve().parents[2] / "modules/procurement/order_creation_guards.sql").read_text(encoding="utf-8")
    proof_sql = "CREATE TABLE procurement.order_request_transition_proof" + sql.split(
        "CREATE TABLE procurement.order_request_transition_proof", 1)[1].split(
        "CREATE OR REPLACE FUNCTION procurement.guard_order_creation()", 1)[0]
    async with pg_factory() as session:
        connection = await session.connection()
        if not await session.scalar(text("SELECT to_regclass('procurement.order_request_transition_proof')")):
            await connection.exec_driver_sql(proof_sql)
        org = Organization(name="Synthetic proof", unp="999999907")
        request = PurchaseRequest(number="PROOF", supplier="Synthetic", item="Component", qty=3, amount=12, stage="approval")
        session.add_all([org, request])
        await session.flush()
        owner = PurchaseOwnership(organization_id=org.id, kind="request", source_id=request.id,
                                  snapshot={}, evidence="Synthetic fixture", actor="proof-test")
        session.add(owner)
        await session.commit()
        request_id = request.id
        with pytest.raises(DBAPIError, match="must originate"):
            async with session.begin_nested():
                await session.execute(text("INSERT INTO procurement.order_request_transition_proof VALUES (:id,txid_current(),'{}')"), {"id": request_id})
        async with session.begin_nested():
            await session.execute(text("UPDATE procurement.purchase_request SET stage='po',item='Changed' WHERE id=:id"), {"id": request_id})
            row = (await session.execute(text("SELECT snapshot, root_transaction=txid_current() FROM procurement.order_request_transition_proof WHERE request_id=:id"), {"id": request_id})).one()
            assert row[1] is True
            assert row[0]["stage"] == "approval" and row[0]["item"] == "Component"
        for statement in ("UPDATE procurement.order_request_transition_proof SET snapshot='{}'",
                          "DELETE FROM procurement.order_request_transition_proof", "TRUNCATE procurement.order_request_transition_proof"):
            with pytest.raises(DBAPIError, match="immutable"):
                async with session.begin_nested():
                    await session.execute(text(statement))
        await session.rollback()
        assert not await session.scalar(text("SELECT EXISTS(SELECT 1 FROM procurement.order_request_transition_proof)"))
