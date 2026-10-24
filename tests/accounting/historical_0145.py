"""Restore genuine synthetic history and exercise its pinned business consumer."""
import asyncio
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from collections import Counter
from pathlib import Path

from sqlalchemy import text

from tests.accounting.test_zero_value_output_cost_postgres import run_migration

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures/accounting/historical0145'
FIXTURE_MANIFEST = json.loads((FIXTURES / 'fixtures.json').read_text(encoding='utf-8'))
assert hashlib.sha256((FIXTURES / 'manifest.json').read_bytes()).hexdigest() == FIXTURE_MANIFEST['consumerManifestSHA256']
CONSUMER_MANIFEST = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf-8'))


def artifact(pin):
    assert Path(pin['name']).name == pin['name']
    path = FIXTURES / pin['name']
    assert path.resolve().parent == FIXTURES.resolve()
    assert path.stat().st_size == pin['bytes']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == pin['sha256']
    with gzip.open(path, 'rb') as source:
        data = source.read(16 * 1024 * 1024 + 1)
    assert len(data) <= 16 * 1024 * 1024 and len(data) == pin['rawBytes']
    assert hashlib.sha256(data).hexdigest() == pin['rawSHA256']
    return data


def child(factory, phase, case, tmp_path, producer=None, consumer=None):
    script = FIXTURES / 'run_consumer.py'
    assert hashlib.sha256(script.read_bytes()).hexdigest() == CONSUMER_MANIFEST['runnerSHA']
    engine = factory.kw['bind']
    payload = {'url': engine.url.render_as_string(hide_password=False),
               'producer': producer, 'consumer': consumer}
    wire = json.dumps(payload).encode()
    assert len(wire) <= 4096
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'TEMP', 'TMP', 'PATH',
        'PROCESSOR_ARCHITEW6432', 'PROCESSOR_ARCHITECTURE'}}
    log = tmp_path / (case + '-' + phase + '.private.log')
    captured, overflow, errors = bytearray(), [], []
    process, reader = None, None
    terminal = False
    try:
        process = subprocess.Popen([sys.executable, '-I', '-B', str(script), phase, case],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=FIXTURES, env=env)

        def read():
            try:
                while chunk := process.stdout.read(4096):
                    if len(captured) + len(chunk) > 65536:
                        overflow.append(True)
                        if process.poll() is None:
                            process.kill()
                        return
                    captured.extend(chunk)
            except Exception as exc:
                errors.append('read:' + type(exc).__name__)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        process.stdin.write(wire)
        process.stdin.close()
        process.wait(timeout=90)
    except Exception as exc:
        errors.append(type(exc).__name__)
    finally:
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
            except Exception as exc:
                errors.append('kill:' + type(exc).__name__)
            try:
                process.wait(timeout=5)
            except Exception as exc:
                errors.append('wait:' + type(exc).__name__)
            try:
                if reader is not None and reader.ident is not None:
                    reader.join(timeout=5)
            except Exception as exc:
                errors.append('join:' + type(exc).__name__)
            reader_done = reader is None or not reader.is_alive()
            for pipe in (process.stdin, process.stdout):
                try:
                    if pipe is not None and reader_done:
                        pipe.close()
                except Exception as exc:
                    errors.append('pipe:' + type(exc).__name__)
            terminal = process.poll() is not None and reader_done and process.stdin.closed and process.stdout.closed
        with log.open('xb') as output:
            output.write(captured)
        (tmp_path / (case + '-' + phase + '-capture.json')).write_text(json.dumps({
            'terminal': terminal, 'errors': errors, 'overflow': bool(overflow),
            'outputBytes': len(captured), 'exit': None if process is None else process.returncode,
        }))
    assert terminal and not errors and not overflow and process.returncode == 0, str(log)
    data = json.loads(captured)
    assert data['passed'] is True and data['phase'] == phase and data['case'] == case
    assert data['state'] == 'consumer145'
    return data['result']

async def snapshot(factory):
    """All user table multisets and sequence states; binary records retain SQL/JSON NULL."""
    async with factory() as session:
        await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        samples = (await session.scalars(text("""
            SELECT encode(pg_catalog.record_send(ROW(v)), 'hex')
            FROM (VALUES (NULL::json), ('null'::json), ('{}'::json), ('{}'::json)) t(v)
        """))).all()
        assert len(samples) == 4 and len(set(samples)) == 3
        assert samples[0] != samples[1] and samples[2] == samples[3]
        tables = (await session.execute(text("""
            SELECT n.nspname,c.relname,c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE c.relkind IN ('r','p') AND n.nspname <> 'information_schema'
              AND n.nspname NOT LIKE 'pg_%' ORDER BY 1,2
        """))).all()
        result = {'tables': {}, 'sequences': {}, 'mutable': {}, 'sequenceNames': {}}
        for schema, name, oid in tables:
            quoted = '"' + schema.replace('"', '""') + '"."' + name.replace('"', '""') + '"'
            columns = (await session.execute(text("""
                SELECT attnum,attname,atttypid,atttypmod,attnotnull,attidentity,attgenerated
                FROM pg_attribute WHERE attrelid=:oid AND attnum>0 AND NOT attisdropped ORDER BY attnum
            """), {'oid': oid})).all()
            rows = (await session.scalars(text(
                f"SELECT encode(pg_catalog.record_send(t),'hex') FROM {quoted} t ORDER BY 1"
            ))).all()
            result['tables'][schema + '.' + name] = {'columns': [list(row) for row in columns], 'rows': rows}
            if schema == 'accounting' and name in {'organization', 'period'}:
                stable = ['"' + row[1].replace('"', '""') + '"' for row in columns
                          if row[1] not in {'generation', 'evidence'}]
                extra = ',month,evidence,evidence IS NULL AS evidence_sql_null' if name == 'period' else ''
                result['mutable'][name] = [dict(row) for row in (await session.execute(text(
                    f"SELECT id,generation,encode(pg_catalog.record_send(ROW({','.join(stable)})),'hex') AS stable{extra} "
                    f'FROM {quoted} ORDER BY id'
                ))).mappings()]
        sequences = (await session.execute(text("""
            SELECT n.nspname,c.relname,s.seqtypid,s.seqstart,s.seqincrement,s.seqmax,s.seqmin,s.seqcache,s.seqcycle
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_sequence s ON s.seqrelid=c.oid
            WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%' ORDER BY 1,2
        """))).all()
        for row in sequences:
            schema, name, *parameters = row
            quoted = '"' + schema.replace('"', '""') + '"."' + name.replace('"', '""') + '"'
            state = (await session.execute(text(f'SELECT last_value,is_called FROM {quoted}'))).one()
            result['sequences'][schema + '.' + name] = {'parameters': parameters, 'state': list(state)}
        for table in ('entry', 'line', 'audit', 'production_output_cost_revision', 'period_change'):
            result['sequenceNames'][table] = await session.scalar(text('SELECT pg_get_serial_sequence(:table, :column)'),
                {'table': 'accounting.' + table, 'column': 'id'})
        return result

def assert_zero_delta(before, after):
    assert before['tables'].keys() == after['tables'].keys()
    assert before['sequences'].keys() == after['sequences'].keys()
    additions = {'accounting.entry': 2, 'accounting.entry_transaction': 2, 'accounting.line': 5, 'accounting.audit': 3,
                 'accounting.production_output_cost_revision': 1, 'accounting.period_change': 2,
                 'accounting.period_root_basis': 1}
    mutable = {'accounting.organization', 'accounting.period'}
    for name, old in before['tables'].items():
        new = after['tables'][name]
        assert old['columns'] == new['columns'], name
        if name in additions:
            assert not (Counter(old['rows']) - Counter(new['rows'])), name
            assert len(new['rows']) - len(old['rows']) == additions[name], name
        elif name not in mutable:
            assert old['rows'] == new['rows'], name
    # The original book creates one organization and its October period. Each of
    # the two genuine service.post calls invalidates exactly these generations.
    for table in ('organization', 'period'):
        old, new = before['mutable'][table], after['mutable'][table]
        assert len(old) == len(new) == 1
        assert old[0]['stable'] == new[0]['stable']
        assert new[0]['generation'] == old[0]['generation'] + 2
        if table == 'period':
            assert new[0]['month'] == '2026-10'
            assert new[0]['evidence'] == {} and new[0]['evidence_sql_null'] is False
    assert before['sequenceNames'] == after['sequenceNames']
    increments = {before['sequenceNames'][table]: amount for table, amount in {
        'entry': 3, 'line': 5, 'audit': 3, 'production_output_cost_revision': 1, 'period_change': 2}.items()}
    for name, old in before['sequences'].items():
        new = after['sequences'][name]
        assert old['parameters'] == new['parameters'], name
        if name in increments:
            assert old['state'][1] is new['state'][1] is True
            assert new['state'][0] == old['state'][0] + increments[name], name
        else:
            assert old['state'] == new['state'], name

async def portable_snapshot(factory):
    """Cross-database oracle: qualified types and exact column text, never binary type OIDs."""
    quote = lambda value: '"' + value.replace('"', '""') + '"'  # noqa: E731
    result = {'tables': {}, 'sequences': {}}
    async with factory() as session:
        await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        for statement in ["SET LOCAL timezone='UTC'", "SET LOCAL datestyle='ISO,YMD'",
                          "SET LOCAL intervalstyle='postgres'", "SET LOCAL bytea_output='hex'",
                          'SET LOCAL extra_float_digits=3', "SET LOCAL client_encoding='UTF8'"]:
            await session.execute(text(statement))
        samples = (await session.scalars(text("""
            SELECT json_build_array(v::text)::text
            FROM (VALUES (NULL::json), ('null'::json), ('{}'::json), ('{}'::json)) t(v)
        """))).all()
        assert len(samples) == 4 and len(set(samples)) == 3
        assert samples[0] != samples[1] and samples[2] == samples[3]
        tables = (await session.execute(text("""
            SELECT n.nspname,c.relname,c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE c.relkind IN ('r','p') AND n.nspname <> 'information_schema'
              AND n.nspname NOT LIKE 'pg_%' ORDER BY 1,2
        """))).all()
        for schema, name, oid in tables:
            columns = (await session.execute(text("""
                SELECT a.attnum,a.attname,tn.nspname,t.typname,a.atttypmod,a.attnotnull,
                       a.attidentity,a.attgenerated,a.attndims,cn.nspname,co.collname
                FROM pg_attribute a JOIN pg_type t ON t.oid=a.atttypid
                JOIN pg_namespace tn ON tn.oid=t.typnamespace
                LEFT JOIN pg_collation co ON co.oid=a.attcollation
                LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace
                WHERE a.attrelid=:oid AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum
            """), {'oid': oid})).all()
            values = ','.join('t.' + quote(column[1]) + '::text' for column in columns)
            rows = (await session.scalars(text(
                f'SELECT json_build_array({values})::text FROM {quote(schema)}.{quote(name)} t ORDER BY 1'
            ))).all()
            result['tables'][schema + '.' + name] = {'columns': [list(row[1:]) for row in columns], 'rows': sorted(rows)}
        sequences = (await session.execute(text("""
            SELECT n.nspname,c.relname,tn.nspname,t.typname,s.seqstart,s.seqincrement,
                   s.seqmax,s.seqmin,s.seqcache,s.seqcycle
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_sequence s ON s.seqrelid=c.oid JOIN pg_type t ON t.oid=s.seqtypid
            JOIN pg_namespace tn ON tn.oid=t.typnamespace
            WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg_%' ORDER BY 1,2
        """))).all()
        for schema, name, *parameters in sequences:
            state = (await session.execute(text(
                f'SELECT last_value,is_called FROM {quote(schema)}.{quote(name)}'
            ))).one()
            result['sequences'][schema + '.' + name] = {'parameters': parameters, 'state': list(state)}
    return result

def bounded_archive_command(args, archive, capture, *, timeout=60, stdout_limit=16 * 1024 * 1024,
                            stderr_limit=8192):
    """Bound both binary streams and independently terminate every started reader/process."""
    process, output, readers = None, None, []
    errors, overflow = [], []
    stderr, count = bytearray(), [0]
    terminal = False
    try:
        output = archive.open('xb')
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

        def read_stdout():
            try:
                while chunk := process.stdout.read(4096):
                    if count[0] + len(chunk) > stdout_limit:
                        overflow.append('stdout')
                        if process.poll() is None:
                            process.kill()
                        return
                    output.write(chunk)
                    count[0] += len(chunk)
            except Exception as exc:
                errors.append('stdout:' + type(exc).__name__)

        def read_stderr():
            try:
                while chunk := process.stderr.read(4096):
                    if len(stderr) + len(chunk) > stderr_limit:
                        overflow.append('stderr')
                        if process.poll() is None:
                            process.kill()
                        return
                    stderr.extend(chunk)
            except Exception as exc:
                errors.append('stderr:' + type(exc).__name__)

        readers = [threading.Thread(target=read_stdout, daemon=True),
                   threading.Thread(target=read_stderr, daemon=True)]
        for reader in readers:
            reader.start()
        process.wait(timeout=timeout)
    except Exception as exc:
        errors.append(type(exc).__name__)
    finally:
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
            except Exception as exc:
                errors.append('kill:' + type(exc).__name__)
            try:
                process.wait(timeout=5)
            except Exception as exc:
                errors.append('wait:' + type(exc).__name__)
            for reader in readers:
                try:
                    if reader.ident is not None:
                        reader.join(timeout=5)
                except Exception as exc:
                    errors.append('join:' + type(exc).__name__)
            if any(reader.is_alive() for reader in readers):
                errors.append('reader-not-terminal')
            else:
                for pipe in (process.stdout, process.stderr):
                    try:
                        pipe.close()
                    except Exception as exc:
                        errors.append('pipe:' + type(exc).__name__)
            terminal = (process.poll() is not None and not any(reader.is_alive() for reader in readers)
                        and process.stdout.closed and process.stderr.closed)
        if output is not None and not any(reader.is_alive() for reader in readers):
            try:
                output.flush()
                os.fsync(output.fileno())
                output.close()
            except Exception as exc:
                errors.append('file:' + type(exc).__name__)
    result = {'terminal': terminal, 'errors': errors, 'overflow': overflow,
              'stdoutBytes': count[0], 'stderrBytes': len(stderr),
              'exit': None if process is None else process.returncode}
    with capture.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    with capture.with_suffix('.stderr.private.bin').open('xb') as stream:
        stream.write(stderr)
    return result

async def restore(factory, tmp_path, case):
    pins = FIXTURE_MANIFEST['cases'][case]
    archive_bytes, canonical_bytes = artifact(pins['archive']), artifact(pins['snapshot'])
    assert archive_bytes[:5] == b'PGDMP'
    canonical = json.loads(canonical_bytes)
    engine = factory.kw['bind']
    url = engine.url
    database, user = url.database, url.username
    assert url.drivername == 'postgresql+psycopg' and url.host in {'127.0.0.1', 'localhost'} and not url.query
    assert re.fullmatch(r'acc_test_[a-f0-9]{32}', database or '')
    assert re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', user or '')
    assert 1024 <= url.port <= 65535
    owner = os.environ['REGISTERED_HEAD_TEST_OWNER']
    assert re.fullmatch(r'[a-f0-9]{32}', owner)
    candidates = {os.environ[key] for key in ('ACCOUNTING_TEST_POSTGRES_CONTAINER', 'ERP_READY_EXPORT_CID') if os.environ.get(key)}
    assert len(candidates) == 1, 'Supply only the matching isolated PostgreSQL service container'
    cid = candidates.pop()
    assert re.fullmatch(r'[a-f0-9]{64}', cid)
    checked = subprocess.run(['docker', 'inspect', '--format',
        '{{.Id}}\n{{.State.Running}}\n{{json (index .NetworkSettings.Ports "5432/tcp")}}', cid],
        capture_output=True, timeout=15, check=True)
    assert len(checked.stdout) <= 8192 and len(checked.stderr) <= 8192
    actual_cid, running, ports = checked.stdout.decode().strip().splitlines()
    assert actual_cid == cid and running == 'true'
    assert any(p['HostIp'] in {'127.0.0.1', '0.0.0.0'} and p['HostPort'] == str(url.port) for p in json.loads(ports))
    fixture_marker, master_marker = 'crm-acc-fixture:' + database, 'crm-registered-head:' + owner
    marker_sql = "SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"
    async with factory() as session:
        assert await session.scalar(text('SELECT current_database()')) == database
        assert 160000 <= int(await session.scalar(text('SHOW server_version_num'))) < 170000
        assert await session.scalar(text(marker_sql)) == fixture_marker
        assert await session.scalar(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname='accounting_test'")) == master_marker
        assert await session.scalar(text('SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()')) == 0
    for db, marker in ((database, fixture_marker), ('accounting_test', master_marker)):
        checked = subprocess.run(['docker', 'exec', cid, 'timeout', '--signal=KILL', '15s',
            'psql', '-X', '-w', '--host=/var/run/postgresql', '--username=' + user,
            '--dbname=' + db, '-At', '-v', 'ON_ERROR_STOP=1', '-c', marker_sql],
            capture_output=True, timeout=20, check=True)
        assert len(checked.stdout) <= 512 and len(checked.stderr) <= 8192
        assert checked.stdout.decode().strip() == marker
    assert await portable_snapshot(factory) == {'tables': {}, 'sequences': {}}
    await engine.dispose()
    archive = tmp_path / (case + '.dump')
    archive.write_bytes(archive_bytes)
    target = '/tmp/accounting-historical-' + database.removeprefix('acc_test_') + '.dump'
    copied = subprocess.run(['docker', 'cp', str(archive), cid + ':' + target], capture_output=True, timeout=30, check=True)
    assert len(copied.stdout) <= 8192 and len(copied.stderr) <= 8192
    checksum = subprocess.run(['docker', 'exec', cid, 'sha256sum', target], capture_output=True, timeout=15, check=True)
    assert len(checksum.stdout) <= 512 and len(checksum.stderr) <= 8192
    assert checksum.stdout.decode().split() == [pins['archive']['rawSHA256'], target]
    result = await asyncio.to_thread(bounded_archive_command,
        ['docker', 'exec', '-e', 'PGOPTIONS=-c statement_timeout=15000 -c lock_timeout=12000', cid,
         'timeout', '--signal=KILL', '60s', 'pg_restore', '--host=/var/run/postgresql',
         '--username=' + user, '--no-password', '--no-owner', '--no-acl', '--exit-on-error',
         '--single-transaction', '--dbname=' + database, target], tmp_path / (case + '-restore.stdout.bin'),
        tmp_path / (case + '-restore-capture.json'), timeout=75)
    assert result['terminal'] and not result['errors'] and not result['overflow'] and result['exit'] == 0
    assert await portable_snapshot(factory) == canonical, 'Restore changed history, columns or sequence states'
    async with factory() as session:
        assert await session.scalar(text("SELECT to_regprocedure('accounting.inventory_allocation_cost_stream(integer,text,text,text,date,integer)')")) is None
        for revision in (['0144_inventory_explicit_allocation_guards.py'] if case == 'zero-existing-issue' else []) + ['0145_inventory_allocation_cost_stream.py']:
            await run_migration(session, revision, 'upgrade')
        await session.commit()
    assert await portable_snapshot(factory) == canonical, 'Migration changed original data or sequence states'
    async with factory() as session:
        assert await session.scalar(text("SELECT to_regprocedure('accounting.inventory_allocation_cost_stream(integer,text,text,text,date,integer)')")) is not None
    return pins['producer']


async def run_historical_case(factory, tmp_path, case):
    producer = await restore(factory, tmp_path, case)
    before = await snapshot(factory)
    consumer = child(factory, 'consume', case, tmp_path, producer=producer)
    after = await snapshot(factory)
    if case.startswith('monetary-'):
        assert consumer == {'salesReplayed': 2, 'correctionsReplayed': 3}
        assert after == before, 'Historical replay changed existing rows or sequences'
    else:
        assert consumer['destinations'] == ['25.00', '75.00'] and consumer['disposalKind'] == 'zero'
        assert_zero_delta(before, after)
        replay = child(factory, 'replay-zero', case, tmp_path, producer=producer, consumer=consumer)
        assert replay == {'revisionId': consumer['revisionId'], 'replayed': True}
        assert await snapshot(factory) == after, 'Zero correction replay changed rows or sequences'
    (tmp_path / (case + '-proof.json')).write_text(json.dumps({
        'case': case, 'restoredAllTables': len(before['tables']), 'restoredAllSequences': len(before['sequences']),
        'canonicalRestoreEqual': True, 'actualMigrationPreservedHistory': True,
        'consumer': consumer, 'replayPreservedHistory': True}, indent=2), encoding='utf-8')
