"""Structural SQL period checks; not full transition/generation certification."""
import json
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting.models import Policy
from modules.accounting.service import CLOSE_STEPS
from tests.accounting.test_postgres import pg_factory  # noqa: F401


async def close_with_evidence(session):
    await session.execute(text('UPDATE accounting.period SET closed=true,closed_generation=generation,evidence=CAST(:evidence AS json)'),
                          {'evidence': json.dumps({key: 'Synthetic checked' for key in CLOSE_STEPS})})


async def seed_verified_policy(session, org):
    session.add(Policy(organization_id=org, effective_from=date(2026, 1, 1), reference='Synthetic',
                       inventory_method='specific', allocation_basis='direct_cost',
                       depreciation_method='straight_line', normative_reference='Synthetic only',
                       normative_verified=True, approved_by='tester'))
    await session.flush()


async def test_pg_period_structure_and_identity(pg_factory):  # noqa: F811
    async with pg_factory() as session:
        org = await session.scalar(text("INSERT INTO accounting.organization(name,unp,generation) VALUES ('Synthetic periods','999999940',0) RETURNING id"))
        await seed_verified_policy(session, org)
        params = {'org': org}
        await session.execute(text("INSERT INTO accounting.period(organization_id,month,closed,generation,evidence) VALUES (:org,'2026-09',false,0,'{}')"), params)
        await session.commit()
        for statement in (
            "UPDATE accounting.period SET month='2026-10'",
            "UPDATE accounting.period SET id=id+1",
            "UPDATE accounting.period SET organization_id=organization_id+1",
            "UPDATE accounting.period SET closed=true",
            "UPDATE accounting.period SET closed_generation=0",
            "UPDATE accounting.period SET generation=-1",
            "UPDATE accounting.period SET evidence='[]'",
            "DELETE FROM accounting.period",
            "TRUNCATE accounting.period CASCADE",
        ):
            with pytest.raises(DBAPIError, match='period|immutable'):
                async with session.begin_nested():
                    await session.execute(text(statement))
        for month, closed, generation in [('0000-01', False, 0), ('2026-13', False, 0),
                                          ('2026-10', True, 0), ('2026-10', False, 2)]:
            with pytest.raises(DBAPIError, match='period'):
                async with session.begin_nested():
                    await session.execute(text("""INSERT INTO accounting.period
                        (organization_id,month,closed,generation,closed_generation,evidence)
                        VALUES (:org,:month,:closed,:generation,:closed_generation,'{}')"""),
                        {**params, 'month': month, 'closed': closed, 'generation': generation,
                         'closed_generation': generation if closed else None})
        assert await session.scalar(text("SELECT count(*) FROM accounting.period")) == 1
        assert await session.scalar(text("SELECT count(*) FROM accounting.period_change")) == 1
        for statement in (
            "UPDATE accounting.period_change SET after_row=after_row",
            "DELETE FROM accounting.period_change",
            "TRUNCATE accounting.period_change",
        ):
            with pytest.raises(DBAPIError, match='immutable'):
                async with session.begin_nested():
                    await session.execute(text(statement))
        with pytest.raises(DBAPIError, match='must originate'):
            async with session.begin_nested():
                await session.execute(text("""INSERT INTO accounting.period_change
                    (root_transaction,organization_id,period_id,before_row,after_row)
                    SELECT txid_current(),organization_id,period_id,before_row,after_row
                    FROM accounting.period_change LIMIT 1"""))
        package = await session.begin_nested()
        # Matching final structure cannot conceal a close/open/close cycle.
        await close_with_evidence(session)
        await session.execute(text("UPDATE accounting.period SET closed=false,closed_generation=NULL,generation=generation+1"))
        await close_with_evidence(session)
        changes = (await session.execute(text("""SELECT before_row,after_row FROM accounting.period_change
            WHERE root_transaction=txid_current() ORDER BY id"""))).all()
        assert [row[1]['closed'] for row in changes] == [True, False, True]
        assert changes[0][0]['closed'] is False
        assert changes[0][1] == changes[1][0] and changes[1][1] == changes[2][0]
        with pytest.raises(DBAPIError, match='closed state twice'):
            async with session.begin_nested():
                await session.execute(text('SET CONSTRAINTS accounting.valid_period_change_chain IMMEDIATE'))
        await package.rollback()
        assert await session.scalar(text("SELECT count(*) FROM accounting.period_change")) == 1
        assert await session.scalar(text("SELECT closed FROM accounting.period")) is False
        monotonic = await session.begin_nested()
        await session.execute(text("UPDATE accounting.period SET generation=2"))
        with pytest.raises(DBAPIError, match='generation cannot decrease'):
            async with session.begin_nested():
                await session.execute(text("UPDATE accounting.period SET generation=1"))
        await monotonic.rollback()
        await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        await close_with_evidence(session)
        # An earlier successful check is not a certificate for later mutations.
        with pytest.raises(DBAPIError, match='closed state twice|Reopening must clear every later period'):
            async with session.begin_nested():
                await session.execute(text('UPDATE accounting.period SET closed=false,closed_generation=NULL'))
        await session.commit()


async def test_pg_root_basis_keeps_untouched_future_periods(pg_factory):  # noqa: F811
    async with pg_factory() as session:
        org = await session.scalar(text("INSERT INTO accounting.organization(name,unp,generation) VALUES ('Synthetic basis','999999941',0) RETURNING id"))
        await session.execute(text("""INSERT INTO accounting.period(organization_id,month,closed,generation,evidence)
            VALUES (:org,'2026-09',false,0,'{}'),(:org,'2026-12',false,0,'{}')"""), {'org': org})
        await session.commit()
        package = await session.begin_nested()
        await session.execute(text("UPDATE accounting.organization SET generation=generation+1 WHERE id=:org"), {'org': org})
        await session.execute(text("UPDATE accounting.period SET generation=1 WHERE organization_id=:org AND month='2026-09'"), {'org': org})
        basis = (await session.execute(text("""SELECT organization_generation,periods_before FROM accounting.period_root_basis
            WHERE root_transaction=txid_current() AND organization_id=:org"""), {'org': org})).one()
        assert basis[0] == 0
        assert [(p['month'], p['generation']) for p in basis[1]] == [('2026-09', 0), ('2026-12', 0)]
        await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        for statement in ('UPDATE accounting.period_root_basis SET periods_before=periods_before',
                          'DELETE FROM accounting.period_root_basis', 'TRUNCATE accounting.period_root_basis'):
            with pytest.raises(DBAPIError, match='immutable'):
                async with session.begin_nested():
                    await session.execute(text(statement))
        with pytest.raises(DBAPIError, match='captured by a guarded write'):
            async with session.begin_nested():
                await session.execute(text('''INSERT INTO accounting.period_root_basis
                    SELECT txid_current(),organization_id,organization_generation,periods_before,active_closes_before
                    FROM accounting.period_root_basis LIMIT 1'''))
        await package.rollback()
        assert await session.scalar(text('SELECT count(*) FROM accounting.period_root_basis WHERE root_transaction=txid_current()')) == 0


@pytest.mark.parametrize('isolation', ['REPEATABLE READ', 'SERIALIZABLE'])
async def test_pg_guarded_period_requires_read_committed(pg_factory, isolation):  # noqa: F811
    async with pg_factory() as session:
        org = await session.scalar(text("INSERT INTO accounting.organization(name,unp,generation) VALUES ('Synthetic isolation','999999942',0) RETURNING id"))
        await session.commit()
        await session.execute(text('SET TRANSACTION ISOLATION LEVEL ' + isolation))
        with pytest.raises(DBAPIError, match='require READ COMMITTED'):
            await session.execute(text("""INSERT INTO accounting.period
                (organization_id,month,closed,generation,evidence) VALUES (:org,'2026-10',false,0,'{}')"""), {'org': org})
        await session.rollback()
        assert await session.scalar(text('SELECT count(*) FROM accounting.period')) == 0


async def test_pg_cannot_materialize_earlier_open_period(pg_factory):  # noqa: F811
    async with pg_factory() as session:
        org = await session.scalar(text("INSERT INTO accounting.organization(name,unp,generation) VALUES ('Synthetic frontier','999999943',0) RETURNING id"))
        await seed_verified_policy(session, org)
        await session.execute(text("""INSERT INTO accounting.period
            (organization_id,month,closed,generation,evidence) VALUES (:org,'2026-10',false,0,'{}')"""), {'org': org})
        await close_with_evidence(session)
        await session.commit()
        with pytest.raises(DBAPIError, match='before a closed period'):
            async with session.begin_nested():
                await session.execute(text("""INSERT INTO accounting.period
                    (organization_id,month,closed,generation,evidence) VALUES (:org,'2026-09',false,0,'{}')"""), {'org': org})
        await session.execute(text("""INSERT INTO accounting.period
            (organization_id,month,closed,generation,evidence) VALUES (:org,'2026-11',false,0,'{}')"""), {'org': org})
        await session.commit()
        assert await session.scalar(text('SELECT count(*) FROM accounting.period')) == 2
