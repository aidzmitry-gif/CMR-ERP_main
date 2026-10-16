"""Receipt immutability on PostgreSQL; full package certification remains separate."""
import asyncio
import copy
import json
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting import closing_commands, service
from modules.accounting.financial_closing import preview
from modules.accounting.models import Account, FinancialCloseReceipt, FinancialReopenReceipt, Period
from modules.accounting.schemas import FinancialCloseInput, FinancialReopenInput
from tests.accounting.test_financial_closing_commands import close
from tests.accounting.test_financial_closing_preview import post
from tests.accounting.test_financial_closing_preview_postgres import preview_pg  # noqa: F401
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401
from tests.test_shipping_producer_concurrency_postgres import (
    TIMEOUT,
    connection_identity,
    observe_wait,
    ready,
)


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_committed_close_reopen_receipts_cannot_be_rewritten(preview_pg, posting):  # noqa: F811
    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", "180.00")
    await post(pg.api, pg.prefix, posting, pg.policy, "expense", "702", "60", "100.00")
    async with pg.factory() as session:
        _, receipt = await close(session, pg.org)
        await closing_commands.reopen(session, pg.org, "2026-10",
            FinancialReopenInput(request_key=uuid4(), reason="Synthetic verified correction"), "tester")
        await session.commit()
        assert receipt.monthly_entry_id is not None and receipt.annual_entry_id is not None
        for table in ("financial_close_receipt", "financial_reopen_receipt", "financial_reopen_item"):
            assert await session.scalar(text(f"SELECT count(*) FROM accounting.{table}")) == 1
            for sql in (f"UPDATE accounting.{table} SET id=id", f"DELETE FROM accounting.{table}",
                        f"TRUNCATE accounting.{table} CASCADE"):
                with pytest.raises(DBAPIError, match="immutable"):
                    async with session.begin_nested():
                        await session.execute(text(sql))
        assert len(await closing_commands.authenticated_entries(session, pg.org)) == 4
        for sql, error in [
            ("UPDATE accounting.financial_receipt_transaction SET root_transaction=txid_current()", "immutable"),
            ("DELETE FROM accounting.financial_receipt_transaction", "immutable"),
            ("TRUNCATE accounting.financial_receipt_transaction", "immutable"),
            (f"INSERT INTO accounting.financial_receipt_transaction VALUES ('close',999,txid_current(),{pg.org})", "generated"),
            ("INSERT INTO accounting.financial_reopen_item (reopen_receipt_id,close_receipt_id) "
             "SELECT reopen_receipt_id,close_receipt_id FROM accounting.financial_reopen_item LIMIT 1", "original receipt transaction"),
        ]:
            with pytest.raises(DBAPIError, match=error):
                async with session.begin_nested():
                    await session.execute(text(sql))
        # Even a valid recomputed envelope cannot attach an earlier committed entry.
        copied = {k: getattr(receipt, k) for k in (
            "organization_id", "month", "actor", "monthly_entry_id", "annual_entry_id", "snapshot")}
        key = str(uuid4())
        command = {**receipt.command, "request_key": key}
        clone = FinancialCloseReceipt(**copied, request_key=key, command=command,
            command_digest=closing_commands.checksum(command), digest="")
        clone.digest = closing_commands.receipt_checksum(clone)
        with pytest.raises(DBAPIError, match="same organization and root transaction"):
            async with session.begin_nested():
                session.add(clone)
                await session.flush()
        for table, month in (("financial_close_receipt", "month"), ("financial_reopen_receipt", "from_month")):
            with pytest.raises(DBAPIError, match="Invalid financial receipt envelope"):
                async with session.begin_nested():
                    await session.execute(text(f"""INSERT INTO accounting.{table}
                        (organization_id,request_key,{month},command,command_digest,snapshot,digest,actor)
                        SELECT organization_id,:key,{month},command,command_digest,snapshot,digest,actor
                        FROM accounting.{table} LIMIT 1"""), {"key": str(uuid4())})


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
@pytest.mark.parametrize("tamper", ["amount", "dimensions"])
async def test_sql_rejects_balanced_but_incorrect_closing_and_rolls_back(preview_pg, posting, monkeypatch, tamper):  # noqa: F811
    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", "180.00")
    async with pg.factory() as session:
        plan = await preview(session, pg.org, "2026-10", include_basis=True)
        forged = copy.deepcopy(plan)
        # Both sides remain balanced; only independent source calculation exposes this.
        for line in forged["monthly_lines"]:
            line[tamper] = "181.00" if tamper == "amount" else {"department": "forged"}

        async def forged_preview(*args, **kwargs):
            return forged

        monkeypatch.setattr(closing_commands, "preview", forged_preview)
        data = FinancialCloseInput(request_key=uuid4(), expected_basis_digest=plan["basis_digest"],
            expected_generation=plan["period_generation"], evidence={s: "Synthetic reviewed control" for s in service.CLOSE_STEPS})
        with pytest.raises(DBAPIError, match="independent ledger calculation|transfer membership"):
            await closing_commands.confirm(session, pg.org, "2026-10", data, "tester")
        await session.rollback()
        assert await session.scalar(text("SELECT count(*) FROM accounting.entry WHERE organization_id=:org"), {"org": pg.org}) == 1
        assert await session.scalar(text("SELECT count(*) FROM accounting.financial_close_receipt")) == 0
        assert await session.scalar(text("SELECT closed FROM accounting.period WHERE organization_id=:org AND month='2026-10'"), {"org": pg.org}) is False


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_sql_closing_rejects_an_older_account_version_with_the_same_code(preview_pg, posting, monkeypatch):  # noqa: F811
    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", "180.00")
    async with pg.factory() as session:
        old = Account(organization_id=pg.org, code="701", title="Synthetic old asset classification",
            category="asset", valid_from=date(2025, 1, 1), required_dimensions=["department"],
            currency_tracking=False, quantity_tracking=False, cash=False, normative_ref="Synthetic history")
        session.add(old)
        await session.commit()
        original_validate = service.validate_posting

        async def stale_account(*args, **kwargs):
            accounts, policy = await original_validate(*args, **kwargs)
            if kwargs.get("financial_transfer"):
                accounts = {**accounts, "701": old}
            return accounts, policy

        monkeypatch.setattr(service, "validate_posting", stale_account)
        with pytest.raises(DBAPIError, match="effective account version"):
            await close(session, pg.org)
        await session.rollback()
        assert await session.scalar(text("SELECT count(*) FROM accounting.financial_close_receipt")) == 0
        assert await session.scalar(text("SELECT count(*) FROM accounting.entry WHERE organization_id=:org"), {"org": pg.org}) == 1


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
@pytest.mark.parametrize("income,expense,monthly,annual", [(None,None,False,False), ("80.00","180.00",True,True), ("100.00","100.00",True,False)])
async def test_pg_closes_empty_loss_and_zero_result(preview_pg, posting, income, expense, monthly, annual):  # noqa: F811
    pg = preview_pg
    if income is not None:
        await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", income)
        await post(pg.api, pg.prefix, posting, pg.policy, "expense", "702", "60", expense)
    async with pg.factory() as session:
        _, receipt = await close(session, pg.org)
        assert (receipt.monthly_entry_id is not None) is monthly
        assert (receipt.annual_entry_id is not None) is annual
        assert await session.scalar(text("SELECT closed FROM accounting.period WHERE organization_id=:org AND month='2026-10'"), {"org": pg.org}) is True


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_sql_reopening_rejects_balanced_reversal_with_wrong_amount(preview_pg, posting, monkeypatch):  # noqa: F811
    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", "180.00")
    async with pg.factory() as session:
        await close(session, pg.org)
        original = closing_commands.reversal_posting

        def forged_reversal(*args, **kwargs):
            value = original(*args, **kwargs)
            for line in value.lines:
                line.amount += 1
            return value

        monkeypatch.setattr(closing_commands, "reversal_posting", forged_reversal)
        with pytest.raises(DBAPIError, match="exactly reverse the original"):
            await closing_commands.reopen(session, pg.org, "2026-10",
                FinancialReopenInput(request_key=uuid4(), reason="Synthetic reviewed correction"), "tester")
            await session.commit()
        await session.rollback()
        assert await session.scalar(text("SELECT count(*) FROM accounting.financial_reopen_receipt")) == 0
        assert await session.scalar(text("SELECT count(*) FROM accounting.financial_reopen_item")) == 0
        assert await session.scalar(text("SELECT count(*) FROM accounting.entry WHERE operation='period_reopen'")) == 0
        assert await session.scalar(text("SELECT closed FROM accounting.period WHERE organization_id=:org AND month='2026-10'"), {"org": pg.org}) is True


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_early_reversal_validation_does_not_allow_late_balanced_lines(preview_pg, posting):  # noqa: F811
    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", "180.00")
    async with pg.factory() as session:
        await close(session, pg.org)
        receipt = await closing_commands.reopen(session, pg.org, "2026-10",
            FinancialReopenInput(request_key=uuid4(), reason="Synthetic reviewed correction"), "tester")
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        target = receipt.snapshot["items"][0]["monthly_entry_id"]
        with pytest.raises(DBAPIError, match="exactly reverse the original"):
            async with session.begin_nested():
                await session.execute(text("""INSERT INTO accounting.line
                    (entry_id,account_id,account_code,account_title,category,cash,side,amount,dimensions,currency)
                    SELECT entry_id,account_id,account_code,account_title,category,cash,side,amount,dimensions,currency
                    FROM accounting.line WHERE entry_id=:id"""), {"id": target})
        await session.commit()
        assert len(await closing_commands.authenticated_entries(session, pg.org)) == 4


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_sql_reopening_cannot_omit_an_active_later_empty_close(preview_pg):  # noqa: F811
    pg = preview_pg
    async with pg.factory() as session:
        await close(session, pg.org)
        await close(session, pg.org, "2026-11")
        key = str(uuid4())
        command = {"from_month": "2026-10", "request_key": key, "reason": "Synthetic omission attempt"}
        receipt = FinancialReopenReceipt(organization_id=pg.org, request_key=key, from_month="2026-10",
            command=command, command_digest=closing_commands.checksum(command), actor="tester",
            snapshot={"items": [], "periods_before": [], "periods_after": []}, digest="")
        receipt.digest = closing_commands.receipt_checksum(receipt)
        with pytest.raises(DBAPIError, match="include every active close"):
            session.add(receipt)
            await session.commit()
        await session.rollback()
        assert await session.scalar(text("SELECT count(*) FROM accounting.financial_reopen_receipt")) == 0
        assert await session.scalar(text("SELECT count(*) FROM accounting.period WHERE organization_id=:org AND closed"), {"org": pg.org}) == 2
        await closing_commands.reopen(session, pg.org, "2026-10",
            FinancialReopenInput(request_key=uuid4(), reason="Synthetic complete cascade"), "tester")
        await session.commit()
        assert await session.scalar(text("SELECT count(*) FROM accounting.financial_reopen_item")) == 2


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_validated_close_cannot_receive_late_balanced_lines_in_same_transaction(preview_pg, posting):  # noqa: F811
    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", "180.00")
    async with pg.factory() as session:
        plan = await preview(session, pg.org, "2026-10")
        data = FinancialCloseInput(request_key=uuid4(), expected_basis_digest=plan["basis_digest"],
            expected_generation=plan["period_generation"], evidence={s: "Synthetic reviewed control" for s in service.CLOSE_STEPS})
        receipt = await closing_commands.confirm(session, pg.org, "2026-10", data, "tester")
        with pytest.raises(DBAPIError, match="cannot be appended after receipt validation"):
            async with session.begin_nested():
                await session.execute(text("""INSERT INTO accounting.line
                    (entry_id,account_id,account_code,account_title,category,cash,side,amount,dimensions,currency)
                    SELECT entry_id,account_id,account_code,account_title,category,cash,side,amount,dimensions,currency
                    FROM accounting.line WHERE entry_id=:id"""), {"id": receipt.monthly_entry_id})
        await session.commit()
        assert len(await closing_commands.authenticated_entries(session, pg.org)) == 2


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_multirow_receipt_insert_cannot_bypass_one_command_per_root(preview_pg):  # noqa: F811
    pg = preview_pg
    rows = []
    for _ in range(2):
        key = str(uuid4())
        command = {"from_month": "2026-10", "request_key": key, "reason": "Synthetic multirow attempt"}
        receipt = FinancialReopenReceipt(organization_id=pg.org, request_key=key, from_month="2026-10",
            command=command, command_digest=closing_commands.checksum(command), actor="tester",
            snapshot={"items": [], "periods_before": [], "periods_after": []}, digest="")
        receipt.digest = closing_commands.receipt_checksum(receipt)
        rows.append({key: getattr(receipt, key) for key in (
            "organization_id", "request_key", "from_month", "command", "command_digest", "snapshot", "digest", "actor")})
    async with pg.factory() as session:
        with pytest.raises(DBAPIError, match="financial_receipt_one_command_per_root"):
            await session.execute(text("""INSERT INTO accounting.financial_reopen_receipt
                (organization_id,request_key,from_month,command,command_digest,snapshot,digest,actor)
                SELECT organization_id,request_key,from_month,command,command_digest,snapshot,digest,actor
                FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x(organization_id integer,request_key text,
                    from_month text,command jsonb,command_digest text,snapshot jsonb,digest text,actor text)"""),
                {"rows": json.dumps(rows)})
        await session.rollback()
        assert await session.scalar(text("SELECT count(*) FROM accounting.financial_reopen_receipt")) == 0
        assert await session.scalar(text("SELECT count(*) FROM accounting.financial_receipt_transaction")) == 0

@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_reopen_sql_detects_omitted_future_empty_period(preview_pg, monkeypatch):  # noqa: F811
    from types import SimpleNamespace

    pg = preview_pg
    async with pg.factory() as session:
        await close(session, pg.org)
        await close(session, pg.org, "2026-11")
        await session.execute(text("""INSERT INTO accounting.period
            (organization_id,month,closed,generation,evidence) VALUES (:org,'2026-12',false,0,'{}')"""), {'org': pg.org})
        await session.commit()
        original_scalars = session.scalars

        async def omit_future(statement, *args, **kwargs):
            result = await original_scalars(statement, *args, **kwargs)
            descriptions = getattr(statement, 'column_descriptions', [])
            if descriptions and descriptions[0].get('entity') is Period:
                values = [p for p in result.all() if p.month != '2026-12']
                return SimpleNamespace(all=lambda: values)
            return result

        with monkeypatch.context() as patch:
            patch.setattr(session, 'scalars', omit_future)
            with pytest.raises(DBAPIError, match='dependent period generation or state mismatch'):
                await closing_commands.reopen(session, pg.org, '2026-10',
                    FinancialReopenInput(request_key=uuid4(), reason='Synthetic omitted future period'), 'tester')
                await session.commit()
        await session.rollback()
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_reopen_receipt')) == 0
        assert await session.scalar(text('SELECT count(*) FROM accounting.period WHERE closed')) == 2
        await closing_commands.reopen(session, pg.org, '2026-10',
            FinancialReopenInput(request_key=uuid4(), reason='Synthetic full cascade'), 'tester')
        await session.commit()
        assert await session.scalar(text("SELECT generation FROM accounting.period WHERE month='2026-12'")) == 1
        assert await session.scalar(text('SELECT count(*) FROM accounting.period WHERE closed')) == 0


@pytest.mark.parametrize('preview_pg', [True], indirect=True)
@pytest.mark.parametrize('target', ['period', 'organization'])
async def test_close_rechecks_late_generation_after_immediate(preview_pg, target):  # noqa: F811
    pg = preview_pg
    async with pg.factory() as session:
        plan = await preview(session, pg.org, '2026-10')
        body = FinancialCloseInput(request_key=uuid4(), expected_basis_digest=plan['basis_digest'],
            expected_generation=plan['period_generation'],
            evidence={step: 'Synthetic reviewed control' for step in service.CLOSE_STEPS})
        await closing_commands.confirm(session, pg.org, '2026-10', body, 'tester')
        await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        # Keep the Period row internally consistent to reach the package arithmetic check.
        mutation = ('UPDATE accounting.period SET generation=generation+1, '
                    'closed_generation=closed_generation+1 WHERE organization_id=:org'
                    if target == 'period' else
                    'UPDATE accounting.organization SET generation=generation+1 WHERE id=:org')
        with pytest.raises(DBAPIError, match='generation.*mismatch'):
            await session.execute(text(mutation), {'org': pg.org})
        await session.rollback()
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_close_receipt')) == 0
        assert await session.scalar(text('SELECT count(*) FROM accounting.period WHERE closed')) == 0
        assert await session.scalar(text('SELECT generation FROM accounting.organization WHERE id=:org'), {'org': pg.org}) == 0

@pytest.mark.parametrize('preview_pg', [True], indirect=True)
@pytest.mark.parametrize('case', ['stale-close', 'unrelated-entry'])
async def test_reopen_rejects_stale_close_or_unrelated_root_entry(preview_pg, posting, case):  # noqa: F811
    pg = preview_pg
    async with pg.factory() as session:
        await close(session, pg.org)
        if case == 'stale-close':
            # Simulate inconsistent preexisting history; full ordinary generation
            # provenance remains a separate guard. Receipt itself stays immutable.
            await session.execute(text("UPDATE accounting.period SET generation=generation+1,closed_generation=closed_generation+1"))
            await session.commit()
        with pytest.raises(DBAPIError, match='generation is stale' if case == 'stale-close' else 'unrelated entries'):
            await closing_commands.reopen(session, pg.org, '2026-10',
                FinancialReopenInput(request_key=uuid4(), reason='Synthetic negative root validation'), 'tester')
            if case == 'unrelated-entry':
                await service.post(session, pg.org, posting('unrelated-root-entry', '62', '60', '1.00',
                    policy_id=pg.policy, document_date='2026-10-01', operation_date='2026-10-01',
                    posting_date='2026-10-01'), 'tester')
            await session.commit()
        await session.rollback()
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_reopen_receipt')) == 0
        assert await session.scalar(text("SELECT count(*) FROM accounting.entry WHERE source='unrelated-root-entry'")) == 0
        assert await session.scalar(text('SELECT count(*) FROM accounting.period WHERE closed')) == 1

@pytest.mark.parametrize('preview_pg', [True], indirect=True)
@pytest.mark.parametrize('case', ['phantom-generation', 'phantom-immediate', 'omitted-future'])
async def test_close_sql_checks_original_and_dependent_generations(preview_pg, posting, monkeypatch, case):  # noqa: F811
    from types import SimpleNamespace

    pg = preview_pg
    if case == 'omitted-future':
        await post(pg.api, pg.prefix, posting, pg.policy, 'income-before-close', '62', '701', '180.00')
    async with pg.factory() as session:
        if case.startswith('phantom'):
            await session.execute(text("""INSERT INTO accounting.period
                (organization_id,month,closed,generation,evidence) VALUES (:org,'2026-10',false,0,'{}')"""), {'org': pg.org})
        else:
            await session.execute(text("""INSERT INTO accounting.period
                (organization_id,month,closed,generation,evidence) VALUES (:org,'2026-12',false,0,'{}')"""), {'org': pg.org})
        await session.commit()
        original_scalars = session.scalars

        async def omit_future(statement, *args, **kwargs):
            result = await original_scalars(statement, *args, **kwargs)
            descriptions = getattr(statement, 'column_descriptions', [])
            if descriptions and descriptions[0].get('entity') is Period:
                values = [p for p in result.all() if p.month != '2026-12']
                return SimpleNamespace(all=lambda: values)
            return result

        with monkeypatch.context() as patch:
            if case == 'phantom-immediate':
                await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
            if case.startswith('phantom'):
                await session.execute(text('UPDATE accounting.period SET generation=7'))
            else:
                patch.setattr(session, 'scalars', omit_future)
            expected = 'initial or organization generation mismatch' if case.startswith('phantom') else 'dependent period generation mismatch'
            with pytest.raises(DBAPIError, match=expected):
                await close(session, pg.org)
        await session.rollback()
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_close_receipt')) == 0
        assert await session.scalar(text('SELECT count(*) FROM accounting.period WHERE closed')) == 0
        if case == 'phantom-immediate':
            await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        await close(session, pg.org)
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_close_receipt')) == 1


@pytest.mark.parametrize('preview_pg', [True], indirect=True)
async def test_close_rejects_active_same_month_history(preview_pg):  # noqa: F811
    pg = preview_pg
    async with pg.factory() as session:
        await close(session, pg.org)
        # The formerly constructible corrupt state is now rejected at its origin.
        with pytest.raises(DBAPIError, match='Financial reopening'):
            await session.execute(text("""UPDATE accounting.period SET closed=false,
                closed_generation=NULL,evidence='{}' WHERE organization_id=:org"""), {'org': pg.org})
            await session.commit()
        await session.rollback()
        with pytest.raises(service.AccountingError, match='Reopen the period before calculating'):
            await close(session, pg.org)
        await session.rollback()
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_close_receipt')) == 1
        assert await session.scalar(text('SELECT count(*) FROM accounting.period WHERE closed')) == 1
        # Exercise the supported reopen and reclose sequence with intact history.
        await closing_commands.reopen(session, pg.org, '2026-10',
            FinancialReopenInput(request_key=uuid4(), reason='Synthetic reviewed reopening'), 'tester')
        await session.commit()
        await close(session, pg.org)
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_close_receipt')) == 2
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_reopen_item')) == 1


@pytest.mark.parametrize('preview_pg', [True], indirect=True)
async def test_close_sql_requires_earlier_periods_closed(preview_pg, monkeypatch):  # noqa: F811
    pg = preview_pg
    async with pg.factory() as session:
        await session.execute(text("""INSERT INTO accounting.period
            (organization_id,month,closed,generation,evidence)
            VALUES (:org,'2026-10',false,0,'{}')"""), {'org': pg.org})
        await session.commit()
        original_scalar = session.scalar
        bypassed = []

        async def hide_earlier_open(statement, *args, **kwargs):
            if 'accounting.period.month < ' in str(statement) and 'accounting.period.closed IS false' in str(statement):
                bypassed.append(True)
                return None
            return await original_scalar(statement, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(session, 'scalar', hide_earlier_open)
            with pytest.raises(DBAPIError, match='Close earlier periods first'):
                await close(session, pg.org, '2026-11')
        await session.rollback()
        assert bypassed
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_close_receipt')) == 0
        assert await session.scalar(text('SELECT count(*) FROM accounting.period')) == 1
        await close(session, pg.org, '2026-10')
        await close(session, pg.org, '2026-11')
        assert await session.scalar(text('SELECT count(*) FROM accounting.period WHERE closed')) == 2


@pytest.mark.parametrize('preview_pg', [True], indirect=True)
@pytest.mark.parametrize('registry', ['inbox', 'source_control'])
async def test_close_sql_rejects_pending_documents(preview_pg, monkeypatch, registry):  # noqa: F811
    pg = preview_pg
    async with pg.factory() as session:
        sql = ("INSERT INTO accounting.inbox (organization_id,event_key,month,payload) "
               "VALUES (:org,'synthetic-pending','2026-10','{}')" if registry == 'inbox' else
               "INSERT INTO accounting.source_control (organization_id,source,version,month) "
               "VALUES (:org,'synthetic-pending',1,'2026-10')")
        await session.execute(text(sql), {'org': pg.org})
        await session.commit()
        original_scalar = session.scalar
        bypassed = []

        async def hide_pending(statement, *args, **kwargs):
            if f'accounting.{registry}.entry_id IS NULL' in str(statement):
                bypassed.append(True)
                return None
            return await original_scalar(statement, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(session, 'scalar', hide_pending)
            with pytest.raises(DBAPIError, match='Unposted documents prevent closing'):
                await close(session, pg.org)
        await session.rollback()
        assert bypassed
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_close_receipt')) == 0
        assert await session.scalar(text(f'SELECT count(*) FROM accounting.{registry} WHERE entry_id IS NULL')) == 1


@pytest.mark.parametrize('preview_pg', [True], indirect=True)
@pytest.mark.parametrize('registry', ['inbox', 'source_control'])
@pytest.mark.parametrize('mutation', ['insert', 'update'])
async def test_close_rechecks_late_pending_document(preview_pg, registry, mutation):  # noqa: F811
    pg = preview_pg
    async with pg.factory() as session:
        sql = ("INSERT INTO accounting.inbox (organization_id,event_key,month,payload) "
               "VALUES (:org,'synthetic-late',:month,'{}')" if registry == 'inbox' else
               "INSERT INTO accounting.source_control (organization_id,source,version,month) "
               "VALUES (:org,'synthetic-late',1,:month)")
        if mutation == 'update':
            await session.execute(text(sql), {'org': pg.org, 'month': '2026-11'})
            await session.commit()
        plan = await preview(session, pg.org, '2026-10')
        body = FinancialCloseInput(request_key=uuid4(), expected_basis_digest=plan['basis_digest'],
            expected_generation=plan['period_generation'],
            evidence={step: 'Synthetic reviewed control' for step in service.CLOSE_STEPS})
        await closing_commands.confirm(session, pg.org, '2026-10', body, 'tester')
        await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        expected_error = ('Inbox source identity is immutable' if registry == 'inbox' and mutation == 'update'
                          else 'Unposted documents prevent closing')
        with pytest.raises(DBAPIError, match=expected_error):
            if mutation == 'insert':
                await session.execute(text(sql), {'org': pg.org, 'month': '2026-10'})
            else:
                version = ',version=version+1' if registry == 'source_control' else ''
                await session.execute(text(f"UPDATE accounting.{registry} SET month='2026-10'{version} WHERE organization_id=:org"), {'org': pg.org})
        await session.rollback()
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_close_receipt')) == 0
        assert await session.scalar(text(f"SELECT count(*) FROM accounting.{registry} WHERE month='2026-10'")) == 0
        # A pending document in a later month does not prevent closing October.
        if mutation == 'insert':
            await session.execute(text(sql), {'org': pg.org, 'month': '2026-11'})
            await session.commit()
        await close(session, pg.org)
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_close_receipt')) == 1


@pytest.mark.parametrize('preview_pg', [True], indirect=True)
@pytest.mark.parametrize('registry', ['inbox', 'source_control'])
@pytest.mark.parametrize('commit_source', [True, False])
async def test_close_reads_source_after_real_lock_wait(preview_pg, registry, commit_source, tmp_path):  # noqa: F811
    pg = preview_pg
    started = asyncio.Event()
    trace = {'registry': registry, 'commit_source': commit_source}
    async with pg.factory() as holder:
        trace['holder'] = await connection_identity(holder)
        sql = ("INSERT INTO accounting.inbox (organization_id,event_key,month,payload) "
               "VALUES (:org,'synthetic-lock','2026-10','{}')" if registry == 'inbox' else
               "INSERT INTO accounting.source_control (organization_id,source,version,month) "
               "VALUES (:org,'synthetic-lock',1,'2026-10')")
        await holder.execute(text(sql), {'org': pg.org})

        async def waiting_close():
            async with pg.factory() as session:
                trace['waiter'] = await connection_identity(session)
                original_scalar = session.scalar

                async def hide_application_pending(statement, *args, **kwargs):
                    if f'accounting.{registry}.entry_id IS NULL' in str(statement):
                        return None
                    return await original_scalar(statement, *args, **kwargs)

                session.scalar = hide_application_pending
                started.set()
                try:
                    await close(session, pg.org)
                    return 'closed'
                except DBAPIError as exc:
                    assert 'Unposted documents prevent closing' in str(exc)
                    await session.rollback()
                    return 'blocked'

        task = asyncio.create_task(waiting_close())
        try:
            await ready(started, task)
            assert trace['holder']['pid'] != trace['waiter']['pid']
            assert trace['holder']['txid'] != trace['waiter']['txid']
            trace['lock'] = await observe_wait(pg, trace['waiter']['pid'], trace['holder']['pid'])
            assert 'accounting.organization' in trace['lock']['query']
            if commit_source:
                await holder.commit()
            else:
                await holder.rollback()
            trace['result'] = await asyncio.wait_for(task, TIMEOUT)
            assert trace['result'] == ('blocked' if commit_source else 'closed')
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await holder.rollback()
            (tmp_path / 'closing-source-lock.json').write_text(json.dumps(trace, indent=2), encoding='utf-8')
    async with pg.factory() as session:
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_close_receipt')) == (0 if commit_source else 1)
        assert await session.scalar(text(f'SELECT count(*) FROM accounting.{registry}')) == (1 if commit_source else 0)


@pytest.mark.parametrize('preview_pg', [True], indirect=True)
@pytest.mark.parametrize('registry', ['inbox', 'source_control'])
async def test_document_registry_month_is_canonical(preview_pg, registry):  # noqa: F811
    pg = preview_pg
    async with pg.factory() as session:
        sql = ("INSERT INTO accounting.inbox (organization_id,event_key,month,payload) "
               "VALUES (:org,'synthetic-month',:month,'{}')" if registry == 'inbox' else
               "INSERT INTO accounting.source_control (organization_id,source,version,month) "
               "VALUES (:org,'synthetic-month',1,:month)")
        for month in ['2026-9', '2026-00', '2026-13', '0000-01', 'invalid']:
            with pytest.raises(DBAPIError, match=f'{registry}_canonical_month'):
                async with session.begin_nested():
                    await session.execute(text(sql), {'org': pg.org, 'month': month})
        await session.execute(text(sql), {'org': pg.org, 'month': '2026-09'})
        await session.commit()
        version = ',version=version+1' if registry == 'source_control' else ''
        expected_error = 'Inbox source identity is immutable' if registry == 'inbox' else f'{registry}_canonical_month'
        with pytest.raises(DBAPIError, match=expected_error):
            await session.execute(text(f"UPDATE accounting.{registry} SET month='2026-9'{version}"))
        await session.rollback()
        assert await session.scalar(text(f'SELECT month FROM accounting.{registry}')) == '2026-09'


@pytest.mark.parametrize('preview_pg', [True], indirect=True)
@pytest.mark.parametrize('immediate', [False, True])
@pytest.mark.parametrize('income', [False, True])
async def test_raw_manual_reopen_cannot_bypass_active_financial_close(preview_pg, posting, immediate, income):  # noqa: F811
    pg = preview_pg
    if income:
        await post(pg.api, pg.prefix, posting, pg.policy, 'income', '62', '701', '180.00')
    async with pg.factory() as session:
        await close(session, pg.org)
        if immediate:
            await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        with pytest.raises(DBAPIError, match='financial|Financial'):
            await session.execute(text("UPDATE accounting.period SET closed=false,closed_generation=NULL,evidence='{}' WHERE organization_id=:org"), {'org': pg.org})
            await session.commit()
        await session.rollback()
        assert await session.scalar(text('SELECT closed FROM accounting.period WHERE organization_id=:org'), {'org': pg.org}) is True
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_reopen_receipt')) == 0


@pytest.mark.parametrize('preview_pg', [True], indirect=True)
@pytest.mark.parametrize('income', [False, True])
async def test_financial_reopen_supports_immediate_on_entry(preview_pg, posting, income):  # noqa: F811
    pg = preview_pg
    if income:
        await post(pg.api, pg.prefix, posting, pg.policy, 'income', '62', '701', '180.00')
    async with pg.factory() as session:
        await close(session, pg.org)
        await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        receipt = await closing_commands.reopen(session, pg.org, '2026-10',
            FinancialReopenInput(request_key=uuid4(), reason='Synthetic immediate reopening'), 'tester')
        await session.commit()
        assert receipt.id is not None
        assert await session.scalar(text('SELECT closed FROM accounting.period WHERE organization_id=:org'), {'org': pg.org}) is False
        assert await session.scalar(text('SELECT count(*) FROM accounting.financial_reopen_item')) == 1
