#!/usr/bin/env python3
"""Explicit isolated fresh-copy upgrade and second restore; never production apply."""
import argparse
import datetime
import json
import os
import re
import signal
import socket
import subprocess
import time
import uuid
from pathlib import Path

from prepare_mixed import (
    CHAIN,
    HEAD,
    OPT_IN,
    digest,
    file_sha,
    inspect,
    known_absent,
    probe,
    projection,
    protected_new_directory,
    require,
    run,
    sha,
    verify_image,
    write_json,
)

PG_IMAGE = 'sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc'
SERVER_ROOT = Path('/opt/cmr-erp-rehearsals/CRM-REL-001')


def quote(value):
    return '"' + value.replace('"', '""') + '"'


def query(container, database, sql):
    # All data comparisons occur on owned copies; their rows never leave server.
    return run(['docker', 'exec', container, 'psql', '-X', '-U', 'aios', '-d', database,
                '-At', '-v', 'ON_ERROR_STOP=1', '-c',
                'BEGIN READ ONLY; SET LOCAL statement_timeout=10000; ' + sql + '; COMMIT;'])


def value(container, database, sql):
    output = query(container, database, sql).decode().splitlines()
    return [line for line in output if line not in ('BEGIN', 'SET', 'COMMIT')]


def schema(container, database):
    return value(container, database, 'SELECT version_num FROM alembic_version ORDER BY version_num')


def specs(container):
    sql = """SELECT json_build_object('schema',c.table_schema,'table',c.table_name,
 'columns',json_agg(c.column_name ORDER BY c.ordinal_position),
 'keys',json_agg(c.column_name ORDER BY c.ordinal_position) FILTER (WHERE EXISTS
 (SELECT 1 FROM information_schema.key_column_usage k JOIN information_schema.table_constraints tc
 ON tc.constraint_schema=k.constraint_schema AND tc.constraint_name=k.constraint_name
 AND tc.table_schema=k.table_schema AND tc.table_name=k.table_name
 WHERE k.table_schema=c.table_schema AND k.table_name=c.table_name AND k.column_name=c.column_name
 AND tc.constraint_type IN ('PRIMARY KEY','FOREIGN KEY'))),
 'numeric',json_agg(c.column_name ORDER BY c.ordinal_position) FILTER
 (WHERE c.data_type IN ('numeric','smallint','integer','bigint')))
 FROM information_schema.columns c JOIN information_schema.tables t USING (table_schema,table_name)
 WHERE c.table_schema NOT IN ('information_schema','pg_catalog')
 AND t.table_type='BASE TABLE' AND c.table_name<>'alembic_version'
 GROUP BY c.table_schema,c.table_name ORDER BY c.table_schema,c.table_name"""
    return [json.loads(line) for line in value(container, 'aios_before', sql)]


def rows(container, database, sql, columns):
    bodies = value(container, database,
                   'SELECT to_jsonb(r)::text FROM (' + sql + ') r ORDER BY to_jsonb(r)::text')
    require(all(set(json.loads(line, parse_float=str, parse_int=str)) == set(columns)
                for line in bodies), 'ROW_ORACLE_COLUMN_SHAPE')
    return {'rows': len(bodies), 'sha256': sha('\n'.join(bodies).encode())}


def fingerprint(container, database, spec, *, sql=None, columns=None):
    columns = spec['columns'] if columns is None else columns
    relation = quote(spec['schema']) + '.' + quote(spec['table'])
    source = sql or ('SELECT ' + ','.join(map(quote, columns)) + ' FROM ' + relation)
    result = rows(container, database, source, columns)
    sums = {}
    for column in spec['numeric'] or []:
        if column in columns:
            observed = value(container, database, 'SELECT COALESCE(sum(' + quote(column) +
                             ')::text,\'NULL\') FROM (' + source + ') n')
            require(len(observed) == 1, 'DECIMAL_SUM_SHAPE')
            sums[column] = observed[0]  # PostgreSQL exact numeric text, never float.
    result['decimal_sums'] = sums
    return result


def transformation_map(contract, original_specs):
    require(contract.get('format') == 1 and contract.get('chain') == CHAIN,
            'DATA_CONTRACT_IDENTITY')
    known = {s['schema'] + '.' + s['table']: s for s in original_specs}
    result = {}
    for item in contract['transformations']:
        name = item['table']
        require(name in known and name not in result, 'UNKNOWN_OR_DUPLICATE_TRANSFORMATION')
        columns = item['columns']
        require(columns and len(columns) == len(set(columns)) and
                set(columns) < set(known[name]['columns']) and
                not set(columns).intersection(known[name]['keys'] or []), 'TRANSFORM_COLUMNS')
        require(item['oracle_sql'].lstrip().upper().startswith('SELECT ') and
                ';' not in item['oracle_sql'], 'TRANSFORM_READ_ORACLE')
        result[name] = item
    require(contract.get('link_checks') and all(c['name'] and c['sql'].lstrip().upper().startswith('SELECT ')
            and ';' not in c['sql'] for c in contract['link_checks']), 'EXPLICIT_LINK_CHECKS_REQUIRED')
    require(len({c['name'] for c in contract['link_checks']}) == len(contract['link_checks']),
            'DUPLICATE_LINK_CHECK')
    return result


def snapshot(container, database, original_specs, transformations=None):
    result = {}
    for spec in original_specs:
        name = spec['schema'] + '.' + spec['table']
        transform = (transformations or {}).get(name)
        result[name] = fingerprint(container, database, spec,
                                   sql=transform['oracle_sql'] if transform else None)
    return result


def unchanged_columns(container, database, original_specs, transformations):
    return {s['schema'] + '.' + s['table']: fingerprint(container, database, s,
            columns=[c for c in s['columns'] if c not in transformations[s['schema'] + '.' + s['table']]['columns']])
            for s in original_specs if s['schema'] + '.' + s['table'] in transformations}


def links(container, database, contract):
    return {c['name']: value(container, database, c['sql']) for c in contract['link_checks']}


def owned(container_id, name, owner, dump, production_mounts):
    info = inspect(container_id)
    host = info['HostConfig']
    require(re.fullmatch('[a-f0-9]{64}', container_id) and info['Id'] == container_id and
            info['Name'] == '/' + name and info['Image'] == PG_IMAGE and
            info['Config']['Labels'].get('crm-rel-001-owner') == owner, 'COPY_IDENTITY')
    require(host['NetworkMode'] == 'none' and not host['PortBindings'] and
            not host['Privileged'], 'COPY_NETWORK_BOUNDARY')
    require(host['Binds'] == [str(dump) + ':/backup/database.dump:ro'], 'COPY_BIND_BOUNDARY')
    require(not production_mounts.intersection(m['Source'] for m in info['Mounts']),
            'PRODUCTION_VOLUME_SHARED')
    require(all((m['Type'] == 'bind' and m['Source'] == str(dump) and
                 m['Destination'] == '/backup/database.dump' and not m['RW']) or
                (m['Type'] == 'volume' and m['Destination'] == '/var/lib/postgresql/data')
                for m in info['Mounts']), 'COPY_EXTRA_MOUNT')


def create_copy(name, owner, dump, state, production_mounts, output):
    found = subprocess.run(['docker', 'inspect', name], capture_output=True, timeout=30)
    require(known_absent(found),
            'COPY_EXISTS_NO_RETRY')
    state[name] = None
    write_json(output / 'owned-state.json', state)
    body = run(['docker', 'run', '-d', '--pull=never', '--name', name,
                '--label', 'crm-rel-001-owner=' + owner, '--network=none',
                '--security-opt=no-new-privileges', '--memory=1g', '--cpus=1',
                '--pids-limit=256', '-e', 'POSTGRES_USER=aios', '-e', 'POSTGRES_DB=aios_before',
                '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
                '-v', str(dump) + ':/backup/database.dump:ro', PG_IMAGE], timeout=60)
    container = body.decode().strip()
    require(re.fullmatch('[a-f0-9]{64}', container), 'COPY_ID_FORMAT')
    state[name] = container
    write_json(output / 'owned-state.json', state)
    owned(container, name, owner, dump, production_mounts)
    for _ in range(45):
        ready = subprocess.run(['docker', 'exec', container, 'pg_isready', '-U', 'aios'],
                               capture_output=True, timeout=10)
        if ready.returncode == 0:
            return container
        time.sleep(1)
    raise RuntimeError('COPY_NOT_READY')


def restore(container, database):
    if database != 'aios_before':
        run(['docker', 'exec', container, 'createdb', '-U', 'aios', database])
    run(['docker', 'exec', container, 'pg_restore', '-U', 'aios', '-d', database,
         '--exit-on-error', '--no-owner', '--no-privileges', '/backup/database.dump'], timeout=300)


def cleanup(state, owner, dump, production_mounts):
    failed = False
    for name, container in state.items():
        try:
            if container is None:
                found = subprocess.run(['docker', 'inspect', name], capture_output=True, timeout=30)
                if found.returncode:
                    require(known_absent(found), 'COPY_STATE_UNKNOWN')
                    continue
                container = json.loads(found.stdout)[0]['Id']
            owned(container, name, owner, dump, production_mounts)
            run(['docker', 'rm', '-f', '-v', container])
            found = subprocess.run(['docker', 'inspect', name], capture_output=True, timeout=30)
            require(known_absent(found), 'COPY_CLEANUP_UNCONFIRMED')
        except Exception:
            failed = True
    require(not failed, 'COPY_CLEANUP_UNCONFIRMED')


def rehearsal(args):
    require(os.geteuid() == 0 and socket.gethostname() == 'localhost.localdomain', 'WRONG_SERVER')
    require(args.output.parent == SERVER_ROOT and not args.output.is_symlink(), 'PRIVATE_SERVER_OUTPUT')
    require(sha(args.manifest.read_bytes()) == args.manifest_sha256 and
            sha(args.data_contract.read_bytes()) == args.data_contract_sha256 and
            sha(args.baseline.read_bytes()) == args.baseline_sha256, 'INPUT_HASH_CHANGED')
    manifest = json.loads(args.manifest.read_bytes())
    contract = json.loads(args.data_contract.read_bytes())
    baseline = json.loads(args.baseline.read_bytes())
    require(baseline['schema'] == ['0116'], 'MEASURED_BASELINE_HEAD_REQUIRED')
    live = inspect('aios-app-1')
    prod = inspect('aios-postgres-1')
    require(live['State']['Running'] and prod['State']['Running'] and
            live['Id'] == baseline['app_id'] and live['Image'] == baseline['app_image'] and
            digest(projection(live)) == baseline['runtime_sha256'], 'LIVE_BASELINE_DRIFT')
    require(prod['Id'] == baseline['pg_id'] and prod['Image'] == PG_IMAGE, 'LIVE_POSTGRES_DRIFT')
    require(schema('aios-postgres-1', 'aios') == baseline['schema'], 'LIVE_SCHEMA_DRIFT')
    production_mounts = {m['Source'] for m in prod['Mounts'] + live['Mounts']}
    saved_handlers = {}
    cleaning = False

    def interrupted(signum, frame):
        if not cleaning:
            raise KeyboardInterrupt('REHEARSAL_INTERRUPTED')

    try:
        for name in ('SIGTERM', 'SIGHUP', 'SIGINT'):
            if hasattr(signal, name):
                signum = getattr(signal, name)
                saved_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, interrupted)
        protected_new_directory(args.output)
        dump = args.output / 'database.dump'
        state = {}
        owner = 'crm-rel-001-g06-' + uuid.uuid4().hex
        receipt = {'status': 'REHEARSAL_RUNNING', 'owner': owner,
                   'time_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'image_proof': None, 'probe_state_root': str(args.output),
                   'manifest_sha256': args.manifest_sha256,
                   'data_contract_sha256': args.data_contract_sha256,
                   'baseline_sha256': args.baseline_sha256, 'production_changes': 0,
                   'backup_kind': 'consistent live-read copy; not write-frozen production rollback backup',
                   'release_ready': False}
        try:
            receipt['image_proof'] = verify_image(manifest, args.image, state_root=args.output)
            with dump.open('xb') as handle:
                result = subprocess.run(['docker', 'exec', 'aios-postgres-1', 'pg_dump', '-U', 'aios',
                    '-d', 'aios', '-Fc', '--lock-wait-timeout=10000'], stdout=handle,
                    stderr=subprocess.PIPE, timeout=300)
            require(result.returncode == 0, 'READ_DUMP_FAILED_OUTPUT_REDACTED')
            dump.chmod(0o600)
            receipt['backup_sha256'], receipt['backup_bytes'] = file_sha(dump), dump.stat().st_size
            first = create_copy(owner + '-upgrade', owner, dump, state, production_mounts, args.output)
            listing = run(['docker', 'exec', first, 'pg_restore', '--list', '/backup/database.dump'])
            (args.output / 'archive.list').write_bytes(listing)
            (args.output / 'archive.list').chmod(0o600)
            restore(first, 'aios_before')
            restore(first, 'aios_copy')
            require(schema(first, 'aios_before') == schema(first, 'aios_copy') == baseline['schema'],
                    'RESTORED_HEAD_MISMATCH')
            original_specs = specs(first)
            require(original_specs, 'ORIGINAL_TABLES_EMPTY')
            transforms = transformation_map(contract, original_specs)
            original = snapshot(first, 'aios_before', original_specs)
            require(snapshot(first, 'aios_copy', original_specs) == original, 'INITIAL_RESTORE_MISMATCH')
            expected = snapshot(first, 'aios_before', original_specs, transforms)
            stable = unchanged_columns(first, 'aios_before', original_specs, transforms)
            original_links = links(first, 'aios_before', contract)
            program = "import subprocess; subprocess.run(['alembic','upgrade','head'],check=True)"
            probe(args.image, program, pg_id=first, state_root=args.output)
            require(schema(first, 'aios_copy') == [HEAD], 'UPGRADE_HEAD_MISMATCH')
            require(snapshot(first, 'aios_copy', original_specs) == expected, 'ORIGINAL_ROWS_OR_DECIMAL_MISMATCH')
            require(unchanged_columns(first, 'aios_copy', original_specs, transforms) == stable,
                    'UNDECLARED_COLUMN_CHANGED')
            require(links(first, 'aios_copy', contract) == original_links, 'KEY_LINK_CHANGED')
            # Repeat actual Alembic execution, rather than assuming idempotence.
            probe(args.image, program, pg_id=first, state_root=args.output)
            require(snapshot(first, 'aios_copy', original_specs) == expected, 'REPEAT_UPGRADE_CHANGED_DATA')
            # Second, independently created PostgreSQL is restored AFTER the upgrade.
            second = create_copy(owner + '-restore', owner, dump, state, production_mounts, args.output)
            restore(second, 'aios_before')
            require(schema(second, 'aios_before') == baseline['schema'] and
                    snapshot(second, 'aios_before', original_specs) == original and
                    links(second, 'aios_before', contract) == original_links, 'SECOND_RESTORE_MISMATCH')
            write_json(args.output / 'data-fingerprints.json',
                       {'original': original, 'expected_after': expected, 'link_checks': original_links})
            receipt.update(status='FRESH_COPY_UPGRADE_AND_SEPARATE_RESTORE_PASS',
                           original_tables=len(original_specs), live_head=baseline['schema'],
                           candidate_head=HEAD, second_restore_after_upgrade=True)
        except (Exception, KeyboardInterrupt) as error:
            receipt['status'] = 'ISOLATED_REHEARSAL_FAILED'
            receipt['safe_code'] = str(error) if re.fullmatch('[A-Z_0-9]+', str(error)) else type(error).__name__
        finally:
            cleaning = True
            try:
                cleanup(state, owner, dump, production_mounts)
                receipt['owned_resources_removed'] = receipt.get('safe_code') != 'PROBE_CLEANUP_UNCONFIRMED'
                if not receipt['owned_resources_removed']:
                    receipt['status'] = 'OWNED_CLEANUP_UNCONFIRMED'
            except Exception as error:
                receipt['status'] = 'OWNED_CLEANUP_UNCONFIRMED'
                receipt['owned_resources_removed'] = False
                receipt['cleanup_safe_code'] = str(error) if re.fullmatch('[A-Z_0-9]+', str(error)) else type(error).__name__
            try:
                current, current_pg = inspect('aios-app-1'), inspect('aios-postgres-1')
                require(current['State']['Running'] and current_pg['State']['Running'] and
                        current['Id'] == baseline['app_id'] and current['Image'] == baseline['app_image'] and
                        digest(projection(current)) == baseline['runtime_sha256'] and
                        current_pg['Id'] == baseline['pg_id'] and current_pg['Image'] == PG_IMAGE and
                        schema('aios-postgres-1', 'aios') == baseline['schema'], 'LIVE_CHANGED_EXTERNALLY')
                receipt['live_baseline_unchanged'] = True
            except Exception as error:
                receipt['live_baseline_unchanged'] = False
                receipt['baseline_safe_code'] = str(error) if re.fullmatch('[A-Z_0-9]+', str(error)) else type(error).__name__
                if receipt['status'] != 'OWNED_CLEANUP_UNCONFIRMED':
                    receipt['status'] = 'LIVE_BASELINE_UNCONFIRMED'
            write_json(args.output / 'receipt.json', receipt)
        print(json.dumps(receipt))
        return 0 if receipt['status'] == 'FRESH_COPY_UPGRADE_AND_SEPARATE_RESTORE_PASS' else 1
    finally:
        for signum, handler in saved_handlers.items():
            signal.signal(signum, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-opt-in', required=True, choices=[OPT_IN])
    for name in ('manifest', 'baseline', 'data-contract'):
        parser.add_argument('--' + name, type=Path, required=True)
        parser.add_argument('--' + name + '-sha256', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    return rehearsal(args)


if __name__ == '__main__':
    raise SystemExit(main())
