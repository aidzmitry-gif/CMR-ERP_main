"""Безопасный load-only путь для локального кэша импорта Bitrix24/1С."""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _write_jsonl(root: Path, name: str, rows: list[dict]) -> None:
    (root / f"{name}.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _make_cache(root: Path) -> None:
    _write_jsonl(root, "bx_users", [{"ID": "1", "NAME": "Test", "LAST_NAME": "User"}])
    _write_jsonl(root, "bx_companies", [{"ID": "10", "TITLE": "Test Company"}])
    _write_jsonl(
        root,
        "bx_contacts",
        [{"ID": "20", "NAME": "Test", "LAST_NAME": "Contact", "COMPANY_ID": "10"}],
    )
    _write_jsonl(root, "bx_requisites", [{"ENTITY_ID": "10", "RQ_INN": "100000001"}])
    _write_jsonl(
        root,
        "bx_deals",
        [
            {
                "ID": "30",
                "TITLE": "Test Deal",
                "STAGE_ID": "WON",
                "CATEGORY_ID": "0",
                "OPPORTUNITY": "10",
                "CURRENCY_ID": "BYN",
                "COMPANY_ID": "10",
                "CONTACT_ID": "20",
                "ASSIGNED_BY_ID": "1",
                "DATE_CREATE": "2024-11-02T10:00:00",
            }
        ],
    )
    _write_jsonl(
        root,
        "bx_leads",
        [
            {
                "ID": "40",
                "TITLE": "Test Lead",
                "STATUS_ID": "NEW",
                "SOURCE_ID": "WEB",
                "ASSIGNED_BY_ID": "1",
                "DATE_CREATE": "2024-11-02T10:00:00",
            }
        ],
    )
    _write_jsonl(
        root,
        "bx_calls",
        [
            {
                "ID": "50",
                "CALL_ID": "50",
                "CALL_START_DATE": "2024-11-02T10:00:00",
                "CALL_DURATION": "10",
                "CALL_FAILED_CODE": "200",
                "CALL_TYPE": "2",
                "CRM_ENTITY_TYPE": "CONTACT",
                "CRM_ENTITY_ID": "20",
                "PORTAL_USER_ID": "1",
            }
        ],
    )
    _write_jsonl(
        root,
        "onec_counterparties",
        [{"Ref_Key": "cp-1", "Description": "Test 1C Company", "ИНН": "100000002"}],
    )
    _write_jsonl(root, "onec_sku", [{"Ref_Key": "sku-1", "Code": "SKU-1", "Description": "Test SKU"}])
    _write_jsonl(
        root,
        "onec_sales",
        [
            {
                "Ref_Key": "sale-1",
                "Контрагент_Key": "cp-1",
                "Number": "S-1",
                "Date": "2024-11-03T10:00:00",
                "Posted": True,
                "СуммаДокумента": "10",
                "Товары": [
                    {
                        "Номенклатура_Key": "sku-1",
                        "Цена": "10",
                        "ЦенаСоСкидкой": "10",
                    }
                ],
            }
        ],
    )


def _make_counterparty_cache(
    root: Path,
    companies: list[dict],
    requisites: list[dict],
    onec_counterparties: list[dict],
) -> None:
    _write_jsonl(root, "bx_companies", companies)
    _write_jsonl(root, "bx_requisites", requisites)
    _write_jsonl(root, "onec_counterparties", onec_counterparties)


def _set_load_environment(monkeypatch, cache: Path, db_path: Path) -> None:
    monkeypatch.setenv("IMPORT_CACHE_DIR", str(cache.resolve()))
    monkeypatch.setenv("AIOS_ENVIRONMENT", "dev")
    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")


def _module():
    return importlib.import_module("scripts.import_month")


def test_import_module_does_not_load_connector_config(monkeypatch):
    sys.modules.pop("connectors.config", None)
    module = _module()
    assert "connectors.config" not in sys.modules
    assert callable(module._connector_config)


def test_load_path_does_not_construct_settings_or_connectors(tmp_path):
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    probe = """
import asyncio
import importlib
import dotenv
import requests
from config.settings import Settings

def forbidden(*args, **kwargs):
    raise AssertionError("forbidden load-only side effect")

Settings.__init__ = forbidden
dotenv.load_dotenv = forbidden
requests.sessions.Session.request = forbidden
module = importlib.import_module("scripts.import_month")
asyncio.run(module.load())
"""
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "AIOS_ENVIRONMENT": "dev",
            "AIOS_DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}",
            "IMPORT_CACHE_DIR": str(cache),
            "IMPORT_FROM": "2024-11-01T00:00:00",
            "IMPORT_TO": "2024-12-01T00:00:00",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Test Company" not in result.stdout


def test_all_preflights_load_guard_before_extraction(tmp_path):
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    probe = """
import requests
import runpy
import sys

def forbidden(*args, **kwargs):
    raise AssertionError("network extraction started before load preflight")

requests.sessions.Session.request = forbidden
sys.argv = ["scripts/import_month.py", "all"]
runpy.run_path("scripts/import_month.py", run_name="__main__")
"""
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "AIOS_ENVIRONMENT": "dev",
            "AIOS_DATABASE_URL": "",
            "IMPORT_CACHE_DIR": str(cache),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "AIOS_DATABASE_URL" in result.stderr
    assert "network extraction started" not in result.stderr


def test_load_guard_requires_explicit_isolated_inputs(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setenv("IMPORT_CACHE_DIR", str(tmp_path.resolve()))
    monkeypatch.setenv("AIOS_ENVIRONMENT", "dev")
    monkeypatch.delenv("AIOS_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="AIOS_DATABASE_URL"):
        module._require_isolated_load()

    monkeypatch.setenv("AIOS_DATABASE_URL", "postgresql+psycopg://example")
    with pytest.raises(RuntimeError, match="sqlite"):
        module._require_isolated_load()

    monkeypatch.setenv("AIOS_DATABASE_URL", "sqlite+aiosqlite:///relative.db")
    with pytest.raises(RuntimeError, match="абсолютный"):
        module._require_isolated_load()


@pytest.mark.asyncio
async def test_cached_load_twice_is_idempotent_and_reconciles_without_network(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    monkeypatch.setenv("IMPORT_CACHE_DIR", str(cache.resolve()))
    monkeypatch.setenv("AIOS_ENVIRONMENT", "dev")
    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: pytest.fail("network"))
    monkeypatch.setattr(module._onec, "get", lambda *args, **kwargs: pytest.fail("network"))

    await module.load()
    capsys.readouterr()
    await module.reconcile()
    first = json.loads(capsys.readouterr().out)

    await module.load()
    capsys.readouterr()
    await module.reconcile()
    second_text = capsys.readouterr().out
    second = json.loads(second_text)

    assert first == second
    assert first["destination"]["fidelity"]["bitrix_deals"]["match"] is True
    assert first["destination"]["load_counts"]["bitrix_deals"] == {
        "source_supported_rows": 1,
        "destination_rows": 1,
    }
    assert first["destination"]["load_counts"]["bitrix_contacts"] == {
        "source_rows": 1,
        "expected_import_rows": 1,
        "destination_rows": 1,
        "deduplicated_source_rows": 0,
    }
    assert first["source"]["products"]["onec_item_refs_missing_sku"] == 0
    assert first["source"]["financial"]["import_contract"] == (
        "pending_receivable_requires_reconciliation"
    )
    assert first["destination"]["financial"]["pending_receivable_rows"] == 1
    assert first["destination"]["financial"]["paid_rows"] == 0
    assert first["destination"]["counts"]["stage_events"] == 0
    assert "Test Company" not in second_text

    from decimal import Decimal

    from sqlalchemy import select

    from modules.sales.models import Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.number == "BX-30"))).scalar_one()
        original_amount = deal.amount
        original_counterparty = deal.counterparty
        deal.amount = Decimal("999.00")
        await session.commit()
    await db.disconnect()
    await module.reconcile()
    amount_mutation = json.loads(capsys.readouterr().out)
    assert amount_mutation["destination"]["semantic"]["bitrix_deals"]["digest"] != first[
        "destination"
    ]["semantic"]["bitrix_deals"]["digest"]
    assert amount_mutation["destination"]["fidelity"]["bitrix_deals"]["match"] is False

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.number == "BX-30"))).scalar_one()
        deal.amount = original_amount
        await session.commit()
    await db.disconnect()
    await module.reconcile()
    restored = json.loads(capsys.readouterr().out)
    assert restored["destination"]["semantic"]["bitrix_deals"] == first["destination"]["semantic"]["bitrix_deals"]

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.number == "BX-30"))).scalar_one()
        deal.counterparty = "Synthetic broken link"
        await session.commit()
    await db.disconnect()
    await module.reconcile()
    link_mutation = json.loads(capsys.readouterr().out)
    assert link_mutation["destination"]["semantic"]["bitrix_deals"]["digest"] != first[
        "destination"
    ]["semantic"]["bitrix_deals"]["digest"]
    assert link_mutation["destination"]["fidelity"]["bitrix_deals"]["match"] is False
    assert original_counterparty == "Test Company"


@pytest.mark.asyncio
async def test_semantic_value_and_link_mutations_require_review(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    monkeypatch.setenv("IMPORT_CACHE_DIR", str(cache.resolve()))
    monkeypatch.setenv("AIOS_ENVIRONMENT", "dev")
    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")

    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from core.domain.models import Contact, Counterparty, CounterpartyAlias
    from modules.sales.models import CallLog, Deal

    async def mutate_and_check(model, where, field, value, entity):
        db = module._isolated_database()
        await db.connect()
        async with db.session_factory() as session:
            row = (await session.execute(select(model).where(where))).scalar_one()
            original = getattr(row, field)
            setattr(row, field, value)
            await session.commit()
        await db.disconnect()

        await module.reconcile()
        report = json.loads(capsys.readouterr().out)
        fidelity = report["destination"]["fidelity"][entity]
        assert fidelity["match"] is False
        assert fidelity["classification"]["status"] == "requires_review"
        assert fidelity["classification"]["allowed_changes"]["rows"] == 0
        assert fidelity["classification"]["requires_review"]["rows"] > 0
        assert fidelity["classification"]["conflicts"]["rows"] > 0

        db = module._isolated_database()
        await db.connect()
        async with db.session_factory() as session:
            row = (await session.execute(select(model).where(where))).scalar_one()
            setattr(row, field, original)
            await session.commit()
        await db.disconnect()
        await module.reconcile()
        capsys.readouterr()

    await mutate_and_check(
        Counterparty,
        Counterparty.id == (
            select(CounterpartyAlias.counterparty_id)
            .where(
                CounterpartyAlias.source == "bitrix",
                CounterpartyAlias.external_ref == "company:10",
            )
            .scalar_subquery()
        ),
        "name",
        "Wrong company name",
        "bitrix_companies",
    )
    await mutate_and_check(
        Counterparty,
        Counterparty.id == (
            select(CounterpartyAlias.counterparty_id)
            .where(
                CounterpartyAlias.source == "bitrix",
                CounterpartyAlias.external_ref == "company:10",
            )
            .scalar_subquery()
        ),
        "unp",
        "999999999",
        "bitrix_companies",
    )
    await mutate_and_check(
        Contact,
        Contact.full_name == "Test Contact",
        "counterparty_id",
        None,
        "bitrix_contacts",
    )
    await mutate_and_check(
        Deal,
        Deal.number == "BX-30",
        "counterparty",
        "Wrong deal link",
        "bitrix_deals",
    )
    await mutate_and_check(
        CallLog,
        CallLog.call_id == "50",
        "contact_id",
        None,
        "bitrix_calls",
    )


@pytest.mark.asyncio
async def test_confirmed_payment_is_preserved_and_legacy_paid_is_reported(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    monkeypatch.setenv("IMPORT_CACHE_DIR", str(cache))
    monkeypatch.setenv("AIOS_ENVIRONMENT", "dev")
    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: pytest.fail("network"))

    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from modules.finance.models import Payment

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        payment = (
            await session.execute(select(Payment).where(Payment.entity_ref == "1c:sale:sale-1"))
        ).scalar_one()
        assert payment.status == "pending"
        assert payment.paid_at is None
        assert payment.due_date is None
        payment.status = "paid"
        await session.commit()
    await db.disconnect()

    await module.reconcile()
    legacy = json.loads(capsys.readouterr().out)
    assert legacy["destination"]["financial"]["paid_rows"] == 1
    assert legacy["destination"]["financial"]["payments_with_allocations"] == 0
    assert legacy["destination"]["financial"]["legacy_paid_without_allocations"] == 1

    from modules.finance.models import PaymentAllocation

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        payment = (
            await session.execute(select(Payment).where(Payment.entity_ref == "1c:sale:sale-1"))
        ).scalar_one()
        session.add(PaymentAllocation(payment_id=payment.id, amount=payment.amount))
        await session.commit()
    await db.disconnect()

    await module.load()
    capsys.readouterr()
    await module.reconcile()
    confirmed = json.loads(capsys.readouterr().out)
    assert confirmed["destination"]["financial"]["paid_rows"] == 1
    assert confirmed["destination"]["financial"]["payments_with_allocations"] == 1
    assert confirmed["destination"]["financial"]["legacy_paid_without_allocations"] == 0


@pytest.mark.asyncio
async def test_counterparty_same_name_different_unp_stays_separate(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_counterparty_cache(
        cache,
        [{"ID": "bx-1", "TITLE": "Same Name"}],
        [{"ENTITY_ID": "bx-1", "RQ_INN": "111111111"}],
        [{"Ref_Key": "onec-1", "Description": "Same Name", "ИНН": "222222222"}],
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from core.domain.models import Counterparty, CounterpartyAlias

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert len((await session.execute(select(Counterparty))).scalars().all()) == 2
        assert len((await session.execute(select(CounterpartyAlias))).scalars().all()) == 2
    await db.disconnect()

    await module.reconcile()
    report = json.loads(capsys.readouterr().out)
    assert report["destination"]["counts"]["counterparties"] == 2
    assert report["destination"]["alias_audit"]["unp_conflict_refs"] == 0
    assert report["destination"]["fidelity"]["bitrix_companies"]["classification"]["status"] == "exact"


@pytest.mark.asyncio
async def test_counterparty_same_unp_different_name_uses_one_master(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_counterparty_cache(
        cache,
        [{"ID": "bx-1", "TITLE": "Bitrix Canonical"}],
        [{"ENTITY_ID": "bx-1", "RQ_INN": "111111111"}],
        [{"Ref_Key": "onec-1", "Description": "OneC Alias", "ИНН": "111111111"}],
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select

    from core.domain.models import Counterparty, CounterpartyAlias

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(Counterparty))).scalar_one() == 1
        assert (await session.execute(select(func.count()).select_from(CounterpartyAlias))).scalar_one() == 2
    await db.disconnect()

    await module.reconcile()
    report = json.loads(capsys.readouterr().out)
    audit = report["destination"]["alias_audit"]
    assert audit["master_rows_with_bitrix_and_onec_aliases"] == 1
    assert audit["by_source"]["1c"]["destination_refs_with_unp"] == 1
    assert report["destination"]["fidelity"]["bitrix_companies"]["match"] is True


@pytest.mark.asyncio
async def test_counterparty_alias_unp_drift_rolls_back_and_is_reported(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_counterparty_cache(
        cache,
        [{"ID": "bx-1", "TITLE": "Stable"}],
        [{"ENTITY_ID": "bx-1", "RQ_INN": "111111111"}],
        [],
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    # Новая запись идёт первой, чтобы проверить rollback всей транзакции после drift.
    _make_counterparty_cache(
        cache,
        [
            {"ID": "bx-2", "TITLE": "Rolled Back"},
            {"ID": "bx-1", "TITLE": "Stable"},
        ],
        [
            {"ENTITY_ID": "bx-2", "RQ_INN": "333333333"},
            {"ENTITY_ID": "bx-1", "RQ_INN": "222222222"},
        ],
        [],
    )
    with pytest.raises(RuntimeError, match="UNP conflict"):
        await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select

    from core.domain.models import Counterparty, CounterpartyAlias

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(Counterparty))).scalar_one() == 1
        assert (await session.execute(select(func.count()).select_from(CounterpartyAlias))).scalar_one() == 1
        master = (await session.execute(select(Counterparty))).scalar_one()
        assert master.unp == "111111111"
    await db.disconnect()

    await module.reconcile()
    report = json.loads(capsys.readouterr().out)
    assert report["destination"]["alias_audit"]["unp_conflict_refs"] == 1


@pytest.mark.asyncio
async def test_private_reconcile_details_preserve_aggregate_and_are_repeatable(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from core.domain.models import Contact, Counterparty, CounterpartyAlias

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        counterparty_id = (
            select(CounterpartyAlias.counterparty_id)
            .where(
                CounterpartyAlias.source == "bitrix",
                CounterpartyAlias.external_ref == "company:10",
            )
            .scalar_subquery()
        )
        company = (await session.execute(select(Counterparty).where(
            Counterparty.id == counterparty_id
        ))).scalar_one()
        company.name = "Changed Company"
        contact = (await session.execute(
            select(Contact).where(Contact.full_name == "Test Contact")
        )).scalar_one()
        contact.counterparty_id = None
        await session.commit()
    await db.disconnect()

    await module.reconcile()
    aggregate_stdout = capsys.readouterr().out
    assert "Test Company" not in aggregate_stdout
    assert "Changed Company" not in aggregate_stdout

    detail_path = (tmp_path / "private" / "details.json").resolve()
    monkeypatch.setenv("IMPORT_RECONCILE_DETAIL_REPORT", str(detail_path))
    await module.reconcile()
    detail_stdout = capsys.readouterr().out
    assert detail_stdout == aggregate_stdout
    private_report = json.loads(detail_path.read_text(encoding="utf-8"))
    rows = private_report["rows"]
    assert [row["source_id"] for row in rows] == ["10", "20"]
    assert rows[0]["changed_fields"] == ["name"]
    assert rows[0]["source"]["name"] == "Test Company"
    assert rows[0]["destination"]["name"] == "Changed Company"
    assert rows[1]["changed_fields"] == ["counterparty_link"]
    assert rows[1]["source"]["counterparty_link"] == "company:10"
    assert rows[1]["destination"]["counterparty_link"] is None
    first_bytes = detail_path.read_bytes()

    await module.reconcile()
    assert capsys.readouterr().out == detail_stdout
    assert detail_path.read_bytes() == first_bytes


def test_private_source_details_include_missing_links_without_default_output(
    monkeypatch, tmp_path
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)

    deals = [json.loads(line) for line in (cache / "bx_deals.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    deals[0] = {**deals[0], "ID": "31", "COMPANY_ID": "999"}
    _write_jsonl(cache, "bx_deals", deals)
    calls = [json.loads(line) for line in (cache / "bx_calls.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    calls[0] = {
        **calls[0],
        "ID": "51",
        "CALL_ID": "51",
        "CRM_ENTITY_TYPE": "COMPANY",
        "CRM_ENTITY_ID": "888",
    }
    calls.append({
        **calls[0],
        "ID": "52",
        "CALL_ID": "52",
        "CRM_ENTITY_TYPE": "CONTACT",
        "CRM_ENTITY_ID": "777",
    })
    _write_jsonl(cache, "bx_calls", calls)
    sales = [json.loads(line) for line in (cache / "onec_sales.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    sales[0] = {
        **sales[0],
        "Контрагент_Key": "cp-missing",
        "Товары": [{"Номенклатура_Key": "sku-missing", "Цена": "10"}],
    }
    sales.append({**sales[0], "Ref_Key": "second-shared-missing-sale"})
    _write_jsonl(cache, "onec_sales", sales)

    monkeypatch.setattr(module, "OUT_DIR", cache)
    detail_rows = []
    report = module._source_reconciliation(detail_rows=detail_rows)
    relations = {row["relation"] for row in detail_rows}
    assert relations == {
        "deals_to_companies",
        "calls_to_companies",
        "calls_to_contacts",
        "onec_sales_to_sku",
        "onec_sales_to_counterparty",
    }
    assert {
        row["source_id"]
        for row in detail_rows
        if row["dataset"].startswith("bitrix_")
    } == {"31", "51", "52"}
    onec_details = [row for row in detail_rows if row["dataset"] == "onec_sales"]
    assert {(row["relation"], row["source_reference_id"]) for row in onec_details} == {
        ("onec_sales_to_sku", "sku-missing"),
        ("onec_sales_to_counterparty", "cp-missing"),
    }
    assert report["links"]["deals_to_companies"]["rows_missing"] == 1
    assert report["links"]["calls_to_companies"]["rows_missing"] == 1
    assert report["links"]["calls_to_contacts"]["rows_missing"] == 1
    assert len(onec_details) == 4
    assert {row["source_id"] for row in onec_details} == {
        str(sales[0]["Ref_Key"]), "second-shared-missing-sale",
    }
    assert report["products"]["onec_item_refs_missing_sku"] == 1
    assert report["products"]["onec_counterparty_refs_missing"] == 1


@pytest.mark.asyncio
async def test_private_detail_path_is_validated_before_any_write(
    monkeypatch, tmp_path
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    aggregate_path = (tmp_path / "aggregate.json").resolve()
    monkeypatch.setenv("IMPORT_RECONCILE_REPORT", str(aggregate_path))
    monkeypatch.setenv("IMPORT_RECONCILE_DETAIL_REPORT", "relative-details.json")
    monkeypatch.setattr(
        module,
        "_isolated_database",
        lambda: pytest.fail("path validation must precede database access"),
    )

    with pytest.raises(RuntimeError, match="IMPORT_RECONCILE_DETAIL_REPORT"):
        await module.reconcile()
    assert not aggregate_path.exists()
    assert not (Path("relative-details.json")).exists()


@pytest.mark.asyncio
async def test_private_report_collision_guard_preserves_inputs_and_skips_db(
    monkeypatch, tmp_path
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    cache_file = cache / "bx_companies.jsonl"
    cache_bytes = cache_file.read_bytes()
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    db_path.write_bytes(b"sqlite-input")
    db_bytes = db_path.read_bytes()
    _set_load_environment(monkeypatch, cache, db_path)
    monkeypatch.setattr(
        module,
        "_isolated_database",
        lambda: pytest.fail("collision validation must precede database access"),
    )

    detail_targets = [cache_file, db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")]
    hardlink = tmp_path / "cache-hardlink.jsonl"
    try:
        os.link(cache_file, hardlink)
    except OSError:
        pass
    else:
        detail_targets.append(hardlink)

    for index, detail_target in enumerate(detail_targets):
        aggregate_path = (tmp_path / f"aggregate-{index}.json").resolve()
        monkeypatch.setenv("IMPORT_RECONCILE_REPORT", str(aggregate_path))
        monkeypatch.setenv("IMPORT_RECONCILE_DETAIL_REPORT", str(detail_target))
        with pytest.raises(RuntimeError, match="IMPORT_RECONCILE_DETAIL_REPORT"):
            await module.reconcile()
        assert cache_file.read_bytes() == cache_bytes
        assert db_path.read_bytes() == db_bytes
        assert not aggregate_path.exists()

    same_path = (tmp_path / "same.json").resolve()
    monkeypatch.setenv("IMPORT_RECONCILE_REPORT", str(same_path))
    monkeypatch.setenv("IMPORT_RECONCILE_DETAIL_REPORT", str(same_path))
    with pytest.raises(RuntimeError, match="IMPORT_RECONCILE_REPORT"):
        await module.reconcile()
    assert not same_path.exists()
