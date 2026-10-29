"""Replay source-bound synthetic histories through real historical SQL guards.

The fixtures were captured from the exact e3ffab79 application and ten module
commits, after its five original scenarios passed on registered0142/0143/0148.
Only the original native-test lifecycle was replaced; assertions and application
code were unchanged. Current application flows are tested separately. No guard,
trigger, model metadata or historical migration is disabled or rewritten here.
"""
import asyncio
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import text

KEYS = {'organization': 'id', 'access_grant': 'id', 'account': 'id', 'policy': 'id',
        'period': 'id', 'entry': 'id', 'line': 'id', 'inbox': 'id',
        'production_output_transfer_receipt': 'entry_id', 'production_output_cost_revision': 'id',
        'inventory_sale_receipt': 'entry_id', 'inventory_zero_value_disposal_receipt': 'id', 'audit': 'id'}
ORDER = tuple(KEYS)
MUTABLE = {'organization': {'generation'}, 'period': {'generation'}}


@asynccontextmanager
async def historical_session(factory):
    async with factory() as session:
        # Fixtures were observed in Europe/Minsk. Declare their timestamp
        # rendering context explicitly, including when CI defaults to UTC.
        # SET LOCAL ends with this test transaction; no server setting changes.
        await session.execute(text("SET LOCAL TIME ZONE 'Europe/Minsk'"))
        yield session


async def transition(factory, revision):
    async with historical_session(factory) as session:
        target = session.bind.url.render_as_string(hide_password=False)
    result = await asyncio.to_thread(subprocess.run, [sys.executable, '-m', 'alembic', 'upgrade', revision],
        cwd=Path(__file__).resolve().parents[2], env={**os.environ, 'AIOS_DATABASE_URL': target, 'AIOS_ENVIRONMENT': 'dev'},
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-2500:]
    async with historical_session(factory) as session:
        assert await session.scalar(text('SELECT version_num FROM alembic_version')) == revision


async def replay(factory, filename, *, before_transition=None):
    path = Path(__file__).with_name('fixtures') / 'zero_sale_history' / filename
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['format'] == 1 and data['synthetic'] is True
    assert data['time_zone'] == 'Europe/Minsk'
    assert data['reference_commit'] == 'e3ffab79c3e1c233267a7373f97e1c2c62b3cf01'
    assert len(data['reference_submodules']) == 10
    expected = {table: {} for table in ORDER}
    columns = {}
    async with historical_session(factory) as session:
        revision = await session.scalar(text('SELECT version_num FROM alembic_version'))
        assert revision == data['initial_revision']
    for transaction in data['transactions']:
        if transaction['revision'] != revision:
            if before_transition is not None:
                await before_transition(factory)
            assert (revision, transaction['revision']) in {('0142', '0143'), ('0143', '0148')}
            await transition(factory, transaction['revision'])
            revision = transaction['revision']
        assert set(transaction['insert']) <= set(ORDER)
        assert set(transaction['update']) <= set(MUTABLE)
        async with historical_session(factory) as session:
            created_periods = []
            for table in ORDER:
                for raw in transaction['insert'].get(table, []):
                    row = json.loads(raw)
                    if table not in columns:
                        columns[table] = set((await session.scalars(text(
                            "SELECT column_name FROM information_schema.columns WHERE table_schema='accounting' AND table_name=:table"
                        ), {'table': table})).all())
                    # Never silently omit a later field to fit an older schema.
                    assert set(row) == columns[table], (filename, revision, table)
                    key = row[KEYS[table]]
                    assert key not in expected[table]
                    names = sorted(columns[table])
                    generated_token = table in ('inventory_zero_value_disposal_receipt', 'production_output_cost_revision')
                    if generated_token:
                        # Omit this column so the native trigger assigns it. Keep
                        # every JSON field in its original stored representation.
                        names.remove('registration_token')
                    projections = [f'data.{field}' for field in names]
                    if table == 'period' and row['generation'] != 0:
                        assert row['closed'] is False and row['closed_generation'] is None
                        projections[names.index('generation')] = '0'
                        created_periods.append(row)
                    await session.execute(text(f'INSERT INTO accounting.{table} ({",".join(names)}) '
                        f'SELECT {",".join(projections)} FROM '
                        f'json_populate_record(NULL::accounting.{table}, CAST(:row AS json)) AS data'), {'row': raw})
                    expected[table][key] = raw
                if table == 'entry':
                    # Entry IDs and entryless-disposal tokens share one sequence.
                    # Restore its observed high-water mark before native triggers
                    # reserve any new token; never assign their token directly.
                    used = [*expected['entry'], *[json.loads(raw)['registration_token']
                            for token_table in ('inventory_zero_value_disposal_receipt', 'production_output_cost_revision')
                            for raw in expected[token_table].values()]]
                    if used:
                        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.entry','id'), :used, true)"),
                                              {'used': max(used)})
                for raw in transaction['update'].get(table, []):
                    row = json.loads(raw)
                    key = row[KEYS[table]]
                    before = json.loads(expected[table][key])
                    changed = {field for field in row if row[field] != before[field]}
                    assert changed and changed <= MUTABLE[table]
                    assignments = ','.join(f'{field}=data.{field}' for field in sorted(changed))
                    await session.execute(text(f'UPDATE accounting.{table} AS target SET {assignments} '
                        f'FROM json_populate_record(NULL::accounting.{table}, CAST(:row AS json)) AS data '
                        f'WHERE target.{KEYS[table]}=data.{KEYS[table]}'), {'row': raw})
                    expected[table][key] = raw
            for row in created_periods:
                await session.execute(text('UPDATE accounting.period SET generation=:generation WHERE id=:id'),
                                      {'generation': row['generation'], 'id': row['id']})
            # Original deferred financial admission guards execute at each
            # original transaction boundary, including monetary/quantity pairs.
            await session.commit()
        async with historical_session(factory) as session:
            for table in ORDER:
                actual = sorted((await session.scalars(text(f'SELECT row_to_json(t)::text FROM accounting.{table} t'))).all())
                assert actual == sorted(expected[table].values()), (filename, revision, table, 'stored bytes differ')
    assert revision == data['final_revision']
    return data
