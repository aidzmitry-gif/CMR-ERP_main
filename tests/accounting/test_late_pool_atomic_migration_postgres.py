"""Isolated PostgreSQL guards for the additive V3 late-pool receipt tables."""
# ruff: noqa: F811 -- imported fixtures register pytest fixtures.

import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import service
from modules.accounting.models import Line
from modules.accounting.production_output_cost_workflow import (
    ProductionOutputCostConfirmInput,
    ProductionOutputCostPreviewInput,
    confirm_output_cost_correction,
    preview_output_cost_correction,
)
from modules.accounting.production_output_transfer import (
    ProductionOutputTransferConfirmInput,
    confirm_output_transfer,
    prepare_output_transfer,
)
from modules.accounting.schemas import LineInput, PostingInput
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_production_output_transfer_postgres import (
    SyntheticProduction,
    _seed_production_book,
    _seed_wip,
    transfer_input,
)
from tests.accounting.test_zero_value_output_cost_postgres import run_migration

pytestmark = pytest.mark.integration


async def _upgrade_to_0153(session):
    for path in sorted(Path("migrations/versions").glob("*.py")):
        if "0140" <= path.name[:4] <= "0153":
            await run_migration(session, path.name, "upgrade")


async def test_0153_up_down_up_without_v3_history(pg_factory):
    async with pg_factory() as session:
        await _upgrade_to_0153(session)
        assert await session.scalar(text("SELECT to_regclass('accounting.late_pool_package')"))
        await run_migration(session, "0153_late_pool_atomic_package.py", "downgrade")
        assert await session.scalar(text("SELECT to_regclass('accounting.late_pool_package')")) is None
        await run_migration(session, "0153_late_pool_atomic_package.py", "upgrade")
        await session.commit()


async def _v3_package_fixture(session, pg_book, policy_id):
    await _upgrade_to_0153(session)
    output_data = transfer_input(policy_id)
    output_preview = await prepare_output_transfer(
        session, pg_book[0], "2026-10", output_data, SyntheticProduction(), object())
    output = await confirm_output_transfer(
        session,
        pg_book[0],
        "2026-10",
        ProductionOutputTransferConfirmInput.model_validate({
            **output_data.model_dump(mode="json"),
            "basis_digest": output_preview["basis_digest"],
            "digest": output_preview["digest"],
        }),
        "tester",
        production=SyntheticProduction(),
        warehouse_gateway=object(),
    )
    late_posting = PostingInput(
        source=f"accounting:late-pool-test:{pg_book[0]}",
        source_version=1,
        operation="inventory_late_cost",
        document_date="2026-10-31",
        operation_date="2026-10-31",
        posting_date="2026-10-31",
        policy_id=policy_id,
        rule_version="late-cost-pool-v3",
        explanation="Synthetic V3 late pool",
        lines=[
            LineInput(account="20", side="debit", amount="2.00",
                      dimensions={"department": "SHOP", "order": "ORDER-42"}),
            LineInput(account="60", side="credit", amount="2.00", dimensions={}),
        ],
    )
    late_entry = await service.post(session, pg_book[0], late_posting, "tester", late_cost=True)
    correction_preview = await preview_output_cost_correction(
        session,
        pg_book[0],
        "2026-10",
        ProductionOutputCostPreviewInput(
            original_entry_id=output.id,
            posting_date="2026-10-31",
            request_evidence="Synthetic V3 package output correction",
        ),
    )
    correction = await confirm_output_cost_correction(
        session,
        pg_book[0],
        "2026-10",
        ProductionOutputCostConfirmInput(
            original_entry_id=output.id,
            posting_date="2026-10-31",
            request_evidence="Synthetic V3 package output correction",
            request_key=uuid4(),
            basis_digest=correction_preview["basis_digest"],
        ),
        "tester",
    )
    origin_line_id = await session.scalar(select(Line.id).where(
        Line.entry_id == late_entry.id, Line.account_code == "20"))
    assert origin_line_id is not None and correction.entry_id is not None
    amount = sum((Decimal(str(item["amount"])) for item in correction_preview["ledger_evidence"]["matrix"]
                  if item["account"] == "43" and item["side"] == "debit"), Decimal(0))
    assert amount == Decimal("2.00")
    command = {
        "command_version": 3,
        "material_outputs": [{"output_entry_id": output.id, "amount_byn": "2.00"}],
    }
    calculation = {"kind": "synthetic-v3", "shares": []}
    posting = late_posting.model_dump(mode="json")
    evidence = correction.preview["ledger_evidence"]
    preview = {
        "organization_id": pg_book[0],
        "command": command,
        "calculation": calculation,
        "posting": posting,
        "basis_digest": "a" * 64,
        "posting_digest": late_entry.digest,
        "outputs": [{
            "output_entry_id": output.id,
            "amount_byn": "2.00",
            "prospective_evidence": evidence,
        }],
    }
    return {
        "organization_id": pg_book[0],
        "late_entry_id": late_entry.id,
        "late_digest": late_entry.digest,
        "source": late_posting.source,
        "command": command,
        "calculation": calculation,
        "posting": posting,
        "preview": preview,
        "output_entry_id": output.id,
        "output_revision_id": correction.id,
        "evidence": evidence,
        "origins": [{
            "source_entry_id": late_entry.id,
            "source_line_id": origin_line_id,
            "amount_byn": "2.00",
        }],
    }


async def _insert_package(session, fixture):
    return await session.scalar(text("""
        INSERT INTO accounting.late_pool_package
          (organization_id,request_key,late_entry_id,command,calculation,preview,posting,basis_digest,digest,actor)
        VALUES (:org,:key,:entry,CAST(:command AS jsonb),CAST(:calculation AS jsonb),
          CAST(:preview AS jsonb),CAST(:posting AS jsonb),:basis,:digest,'tester') RETURNING id
    """), {
        "org": fixture["organization_id"], "key": uuid4(), "entry": fixture["late_entry_id"],
        "command": json.dumps(fixture["command"]), "calculation": json.dumps(fixture["calculation"]),
        "preview": json.dumps(fixture["preview"]), "posting": json.dumps(fixture["posting"]),
        "basis": "a" * 64, "digest": fixture["late_digest"],
    })


async def _bind_source_control(session, fixture):
    await session.execute(text("""
        INSERT INTO accounting.source_control (organization_id,source,version,month,entry_id)
        VALUES (:org,:source,1,'2026-10',NULL)
    """), {
        "org": fixture["organization_id"],
        "source": fixture["source"],
    })
    await session.execute(text("""
        UPDATE accounting.source_control SET entry_id=:entry
        WHERE organization_id=:org AND source=:source AND version=1
    """), {
        "entry": fixture["late_entry_id"],
        "org": fixture["organization_id"],
        "source": fixture["source"],
    })


async def test_0153_requires_complete_links_and_rejects_history_mutation(pg_factory, pg_book):
    policy_id = await _seed_production_book(pg_factory, pg_book)
    await _seed_wip(pg_factory, pg_book, policy_id, [("SHOP", "ORDER-42", "12.50")])
    async with pg_factory() as session:
        fixture = await _v3_package_fixture(session, pg_book, policy_id)
        with pytest.raises(DBAPIError, match="output links are incomplete"):
            async with session.begin_nested():
                await _insert_package(session, fixture)
                await _bind_source_control(session, fixture)
                await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        package_id = await _insert_package(session, fixture)
        await _bind_source_control(session, fixture)
        await session.execute(text("""
            INSERT INTO accounting.late_pool_output_cost_link
              (package_id,output_entry_id,output_revision_id,amount,evidence,origins)
            VALUES (:package,:output,:revision,2.00,CAST(:evidence AS jsonb),CAST(:origins AS jsonb))
        """), {
            "package": package_id,
            "output": fixture["output_entry_id"],
            "revision": fixture["output_revision_id"],
            "evidence": json.dumps(fixture["evidence"]),
            "origins": json.dumps(fixture["origins"]),
        })
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        with pytest.raises(DBAPIError, match="immutable"):
            async with session.begin_nested():
                await session.execute(text(
                    "UPDATE accounting.late_pool_package SET actor='forged' WHERE id=:id"), {"id": package_id})
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.execute(text("""
                    INSERT INTO accounting.late_pool_output_cost_link
                      (package_id,output_entry_id,output_revision_id,amount,evidence,origins)
                    VALUES (:package,:output,:revision,2.00,CAST(:evidence AS jsonb),CAST(:origins AS jsonb))
                """), {
                    "package": package_id,
                    "output": fixture["output_entry_id"],
                    "revision": fixture["output_revision_id"],
                    "evidence": json.dumps(fixture["evidence"]),
                    "origins": json.dumps(fixture["origins"]),
                })
        await session.commit()
        with pytest.raises(DBAPIError, match="Cannot downgrade V3 pool package history"):
            async with session.begin_nested():
                await run_migration(session, "0153_late_pool_atomic_package.py", "downgrade")
