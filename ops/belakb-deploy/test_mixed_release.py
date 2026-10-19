"""Local guard/lifecycle tests only: Docker, PostgreSQL and Git export are mocked."""
import argparse
import ast
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock, patch

import prepare_mixed as package
import rehearse_mixed_copy as copy


@contextlib.contextmanager
def fixtures():
    root = Path(tempfile.gettempdir()).resolve()
    path = root / ('crm-rel-001-g06-test-' + uuid.uuid4().hex)
    path.mkdir(mode=0o755)
    try:
        yield str(path)
    finally:
        resolved = path.resolve()
        assert resolved.parent == root and resolved.name.startswith('crm-rel-001-g06-test-')
        shutil.rmtree(resolved)


class Guards(unittest.TestCase):
    def test_cli_requires_explicit_opt_in_before_any_command(self):
        for module in (package, copy):
            with self.subTest(module=module.__name__), patch('sys.argv', ['tool']), \
                    patch.object(module, 'run') as command, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    module.main()
                self.assertEqual(result.exception.code, 2)
                command.assert_not_called()

    def test_source_scope_refuses_secrets_data_and_generated_files(self):
        for path in ('../main.py', '/main.py', 'config/.env.production', 'core/a.key',
                     'modules/sales/data/customer.json', 'scripts/accounts.xlsx',
                     'core/__pycache__/a.pyc'):
            with self.subTest(path=path), self.assertRaises(package.Blocked):
                package.selected(path)
        self.assertFalse(package.selected('docs/private.pdf'))
        self.assertFalse(package.selected('frontend/.env'))
        self.assertTrue(package.selected('main.py'))

    def test_checkpoint_and_pins_drift_refuse_before_output(self):
        with fixtures() as directory:
            output = Path(directory) / 'new'
            base = {'main.py': ('100644', 'a' * 40)}
            for altered, pins in (({'main.py': ('100644', 'b' * 40)}, package.PINS), (base, {})):
                with patch.object(package, 'tree', side_effect=[(base, package.PINS), (altered, pins)]):
                    with self.assertRaises(package.Blocked):
                        package.prepare(Path(directory) / 'repo', 'c' * 40, output)
                self.assertFalse(output.exists())

    def test_fx_postgres_import_closure_is_selected_without_opening_other_tests(self):
        repo = Path(__file__).resolve().parents[2]
        pending = ['tests/integration/test_purchase_foreign_receipts_postgres.py', 'tests/conftest.py']
        seen = set()
        while pending:
            path = pending.pop()
            if path in seen:
                continue
            seen.add(path)
            self.assertIn(path, package.PROOFS)
            self.assertTrue(package.selected(path))
            for node in ast.walk(ast.parse((repo / path).read_text(encoding='utf8'))):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module] + [node.module + '.' + item.name for item in node.names]
                for module in modules:
                    if module.startswith('tests.'):
                        dependency = module.replace('.', '/') + '.py'
                        if (repo / dependency).is_file() and dependency not in seen:
                            pending.append(dependency)
        self.assertEqual(len(seen), 14)
        self.assertIn('tests/__init__.py', package.PROOFS)
        self.assertIn('tests/integration/__init__.py', package.PROOFS)
        self.assertIn('docs/accounting/migration-proposal.py', package.PROOFS)
        self.assertEqual(package.APPLICATION_CHECKPOINT, 'd96e7b5b1fae0a3ac01dbbc5fd90702cb75cd0fc')
        self.assertEqual(package.PINS['procurement'], 'd8f50e89d5f4fbb796715594a9eb6d1740623dfe')
        for path in ('tests/private.py', 'tests/fixtures/customer.json', 'docs/accounting/private.py'):
            self.assertFalse(package.selected(path))

    def test_source_export_uses_committed_objects_and_replaces_whole_app(self):
        names = package.ROOT_FILES | package.PROOFS | package.CLOSURE_FILES | {'core/runtime/app.py', 'docker/app-entrypoint.sh'}
        root = {name: ('100644', 'a' * 40) for name in names}

        def tree(repository, checkpoint, *, module=False):
            return ({'__init__.py': ('100644', 'b' * 40)}, {}) if module else (root, package.PINS)

        with fixtures() as directory, patch.object(package, 'tree', side_effect=tree), \
                patch.object(package, 'run', return_value=b'# immutable committed fixture\n') as command:
            output = Path(directory) / 'new'
            manifest = package.prepare(Path(directory) / 'repo', 'c' * 40, output)
            recipe = (output / 'context' / 'Dockerfile').read_text()
            self.assertLess(recipe.index('rm -rf /app'), recipe.index('COPY source/'))
            self.assertEqual(package.RUNTIME_ALIAS, 'crm-rel-001-g06-runtime:469fbba3826e')
            self.assertEqual(recipe.splitlines()[0], 'FROM ' + package.RUNTIME_ALIAS)
            self.assertEqual(manifest['runtime_image'], package.RUNTIME)
            self.assertIn('LABEL crm-rel-001-source=' + package.digest(manifest['files']), recipe)
            self.assertIn('crm-rel-001-package=' + manifest['package_checkpoint'], recipe)
            self.assertNotIn('pip install', recipe)
            self.assertNotIn('apt', recipe)
            self.assertEqual(manifest['gitlinks'], package.PINS)
            self.assertTrue(names <= manifest['files'].keys())
            self.assertEqual(manifest['frontend']['status'], 'PENDING_PRODUCTION_OIDC_PACKAGE')
            self.assertTrue(all(call.args[0][-3:-1] == ['cat-file', 'blob']
                                for call in command.call_args_list))

    def test_only_exact_sales_mail_runtime_closure_is_selected_from_ops(self):
        expected = {'ops/sales_mail/__init__.py', 'ops/sales_mail/config.py',
                    'ops/sales_mail/queue.py', 'ops/sales_mail/relay.py'}
        self.assertEqual(package.CLOSURE_FILES, expected)
        self.assertTrue(all(package.selected(name) for name in expected))
        for name in ('ops/sales_mail/.env', 'ops/sales_mail/private.json',
                     'ops/other.py', 'ops/belakb-deploy/prepare.py'):
            self.assertFalse(package.selected(name))

    def test_selected_git_symlink_is_refused(self):
        with patch.object(package, 'run', return_value=b'120000 blob ' + b'a' * 40 + b'\tmain.py\0'):
            with self.assertRaises(package.Blocked):
                package.tree(Path('repo'), 'c' * 40)

    def test_environment_blob_is_never_selected_and_pinned_sql_is_included(self):
        listing = (b'100644 blob ' + b'a' * 40 + b'\tconnectors/.env.example\0' +
                   b'100644 blob ' + b'b' * 40 + b'\tmain.py\0')
        with patch.object(package, 'run', return_value=listing):
            self.assertEqual(set(package.tree(Path('repo'), 'c' * 40)[0]), {'main.py'})
        with patch.object(package, 'run', return_value=b'100644 blob ' + b'c' * 40 + b'\tguard.sql\0'):
            self.assertIn('guard.sql', package.tree(Path('module'), 'c' * 40, module=True)[0])

    def test_dependency_runtime_cannot_be_declared_release_image(self):
        manifest = {'gitlinks': package.PINS, 'application_checkpoint': package.APPLICATION_CHECKPOINT}
        with self.assertRaisesRegex(package.Blocked, 'TEST_RUNTIME_IS_NOT_RELEASE_IMAGE'):
            package.verify_image(manifest, package.RUNTIME, state_root=Path('/explicit-private'))

    def test_probe_timeout_still_attempts_owned_cleanup(self):
        with fixtures() as directory, \
                patch.object(package, 'run', side_effect=package.Blocked('COMMAND_UNAVAILABLE_OR_TIMEOUT')), \
                patch.object(package, 'remove_probe', return_value=None) as cleanup:
            with self.assertRaises(package.Blocked):
                package.probe('sha256:' + 'a' * 64, 'pass', state_root=Path(directory))
            self.assertEqual(cleanup.call_args.args[2], 'none')
            self.assertTrue(cleanup.call_args.args[0].startswith('crm-rel-001-g06-probe-'))

    def test_interrupted_create_has_durable_state_before_docker_and_recovers_cid(self):
        with fixtures() as directory:
            root = Path(directory)

            def interrupted(argv, **kwargs):
                name = argv[argv.index('--name') + 1]
                record = json.loads((root / (name + '.json')).read_text())
                self.assertEqual(record['status'], 'PREPARED_BEFORE_DOCKER_CREATE')
                self.assertEqual(record['owner'], name)
                self.assertEqual(record['image'], 'sha256:' + 'a' * 64)
                self.assertEqual(record['network'], 'none')
                self.assertIsNone(record['container_id'])
                Path(argv[argv.index('--cidfile') + 1]).write_text('b' * 64)
                raise KeyboardInterrupt

            with patch.object(package, 'run', side_effect=interrupted), \
                    patch.object(package, 'remove_probe', return_value='b' * 64) as cleanup:
                with self.assertRaises(KeyboardInterrupt):
                    package.probe('sha256:' + 'a' * 64, 'pass', state_root=root)
                self.assertEqual(cleanup.call_args.kwargs, {'container_id': 'b' * 64})
            record = json.loads(next(root.glob('*.json')).read_text())
            self.assertEqual(record['container_id'], 'b' * 64)
            self.assertEqual(record['status'], 'OWNED_PROBE_REMOVED_OR_ABSENT')

    def test_probe_requires_explicit_state_root_before_any_command(self):
        with patch.object(package, 'run') as command:
            with self.assertRaises(TypeError):
                package.probe('sha256:' + 'a' * 64, 'pass')
            command.assert_not_called()

    def test_probe_cleanup_failure_keeps_recoverable_record_and_cannot_report_success(self):
        with fixtures() as directory:
            root = Path(directory)

            def executed(argv, **kwargs):
                Path(argv[argv.index('--cidfile') + 1]).write_text('b' * 64)
                return b'probe output'

            with patch.object(package, 'run', side_effect=executed), \
                    patch.object(package, 'remove_probe', side_effect=package.Blocked('PROBE_OWNER')):
                with self.assertRaisesRegex(package.Blocked, 'PROBE_CLEANUP_UNCONFIRMED'):
                    package.probe('sha256:' + 'a' * 64, 'pass', state_root=root)
            record = json.loads(next(root.glob('*.json')).read_text())
            self.assertEqual(record['container_id'], 'b' * 64)
            self.assertEqual(record['status'], 'PROBE_EXECUTED')

    @staticmethod
    def abandoned_probe(root):
        name = 'crm-rel-001-g06-probe-' + 'd' * 32
        path = root / (name + '.json')
        record = {'format': 1, 'chain': package.CHAIN, 'name': name, 'owner': name,
                  'image': 'sha256:' + 'a' * 64, 'network': 'none', 'state_root': str(root),
                  'cidfile': str(root / (name + '.cid')), 'container_id': None,
                  'status': 'PREPARED_BEFORE_DOCKER_CREATE'}
        path.write_text(json.dumps(record))
        info = {'Id': 'b' * 64, 'Name': '/' + name, 'Image': record['image'],
                'Config': {'Labels': {'crm-rel-001-owner': name}},
                'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True,
                               'Privileged': False, 'Binds': None, 'PortBindings': None},
                'Mounts': [{'Type': 'tmpfs', 'Destination': '/tmp'}]}
        return path, info

    def test_recovery_after_lost_process_adopts_only_strict_owned_container(self):
        for empty_cid in (False, True):
            with self.subTest(empty_cid=empty_cid), fixtures() as directory:
                path, info = self.abandoned_probe(Path(directory))
                if empty_cid:
                    Path(json.loads(path.read_text())['cidfile']).touch()
                found = subprocess.CompletedProcess([], 0, json.dumps([info]).encode(), b'')
                absent = subprocess.CompletedProcess([], 1, b'[]', b'error: no such object')
                with patch.object(package.subprocess, 'run', side_effect=[found, absent]), \
                        patch.object(package, 'run') as delete:
                    record = package.recover_probe(path)
                    delete.assert_called_once_with(['docker', 'rm', '-f', '-v', 'b' * 64])
                    self.assertEqual(record['container_id'], 'b' * 64)
                    self.assertEqual(record['status'], 'OWNED_PROBE_REMOVED_OR_ABSENT')

    def test_recovery_owner_or_cid_mismatch_refuses_delete_and_keeps_pending_record(self):
        with fixtures() as directory:
            path, info = self.abandoned_probe(Path(directory))
            info['Config']['Labels']['crm-rel-001-owner'] = 'different-owner'
            found = subprocess.CompletedProcess([], 0, json.dumps([info]).encode(), b'')
            with patch.object(package.subprocess, 'run', return_value=found), \
                    patch.object(package, 'run') as delete:
                with self.assertRaisesRegex(package.Blocked, 'PROBE_OWNER'):
                    package.recover_probe(path)
                delete.assert_not_called()
            self.assertEqual(json.loads(path.read_text())['status'], 'PREPARED_BEFORE_DOCKER_CREATE')
            record = json.loads(path.read_text())
            record['container_id'] = 'b' * 64
            path.write_text(json.dumps(record))
            Path(record['cidfile']).write_text('c' * 64)
            with patch.object(package.subprocess, 'run') as inspect:
                with self.assertRaisesRegex(package.Blocked, 'PROBE_CID_MISMATCH'):
                    package.recover_probe(path)
                inspect.assert_not_called()

    def test_known_absence_is_anchored_case_insensitive_and_rejects_other_errors(self):
        for stderr in (b'error: no such object', b'error: no such object: a123\n',
                       b'Error: No such container: own', b'Error response from daemon: No such image: sha256:a123'):
            self.assertTrue(package.known_absent(subprocess.CompletedProcess([], 1, b'[]\n', stderr)))
        for code, output, stderr in ((0, b'', b'error: no such object'),
                (2, b'', b'error: no such object'), (1, b'partial data', b'error: no such object'),
                (1, b'', b'permission denied'), (1, b'', b'error: no such object\npermission denied'),
                (1, b'', b'permission denied: no such object'), (1, b'', b'daemon unavailable')):
            self.assertFalse(package.known_absent(subprocess.CompletedProcess([], code, output, stderr)))

    def test_lowercase_absence_is_safe_for_probe_and_partial_pg_cleanup(self):
        found = subprocess.CompletedProcess([], 1, b'[]\n', b'error: no such object')
        with patch.object(package.subprocess, 'run', return_value=found), \
                patch.object(package, 'run') as probe_delete, patch.object(copy, 'run') as pg_delete:
            package.remove_probe('own', 'sha256:' + 'a' * 64, 'none')
            copy.cleanup({'own': None}, 'owner', Path('/dump'), set())
            probe_delete.assert_not_called()
            pg_delete.assert_not_called()

    def test_probe_and_pg_cleanup_reject_permissions_mixed_errors_and_timeout(self):
        for stderr in (b'permission denied', b'error: no such object\npermission denied'):
            found = subprocess.CompletedProcess([], 1, b'[]', stderr)
            with patch.object(package.subprocess, 'run', return_value=found), \
                    patch.object(package, 'run') as probe_delete, patch.object(copy, 'run') as pg_delete:
                with self.assertRaisesRegex(package.Blocked, 'PROBE_STATE_UNKNOWN'):
                    package.remove_probe('own', 'sha256:' + 'a' * 64, 'none')
                with self.assertRaisesRegex(package.Blocked, 'COPY_CLEANUP_UNCONFIRMED'):
                    copy.cleanup({'own': None}, 'owner', Path('/dump'), set())
                probe_delete.assert_not_called()
                pg_delete.assert_not_called()
        with patch.object(package.subprocess, 'run', side_effect=subprocess.TimeoutExpired('docker', 30)), \
                patch.object(package, 'run') as delete:
            with self.assertRaises(subprocess.TimeoutExpired):
                package.remove_probe('own', 'sha256:' + 'a' * 64, 'none')
            delete.assert_not_called()

    def test_pg_create_accepts_only_known_absence_before_creating(self):
        with fixtures() as directory:
            root = Path(directory)
            found = subprocess.CompletedProcess([], 1, b'[]', b'error: no such object')
            state = {}
            with patch.object(copy.subprocess, 'run', return_value=found), \
                    patch.object(copy, 'run', side_effect=package.Blocked('CREATE_INTERRUPTED')):
                with self.assertRaisesRegex(package.Blocked, 'CREATE_INTERRUPTED'):
                    copy.create_copy('own', 'owner', root / 'dump', state, set(), root)
            self.assertEqual(state, {'own': None})
            for code, stderr in ((0, b''), (1, b'permission denied'),
                                 (1, b'error: no such object\npermission denied')):
                with patch.object(copy.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, b'', stderr)), \
                        patch.object(copy, 'run') as create:
                    with self.assertRaises(package.Blocked):
                        copy.create_copy('other', 'owner', root / 'dump', {}, set(), root)
                    create.assert_not_called()

    def test_transformations_cannot_waive_keys_or_entire_table(self):
        specs = [{'schema': 'public', 'table': 't', 'columns': ['id', 'amount'], 'keys': ['id']}]
        for columns, sql in ((['id'], 'SELECT id,amount FROM public.t'),
                             (['id', 'amount'], 'SELECT id,amount FROM public.t'),
                             (['amount'], 'SELECT id,amount FROM public.t; DELETE FROM public.t')):
            contract = {'format': 1, 'chain': package.CHAIN, 'transformations': [
                {'table': 'public.t', 'columns': columns, 'oracle_sql': sql}],
                'link_checks': [{'name': 'fk', 'sql': 'SELECT count(*) FROM public.t'}]}
            with self.subTest(columns=columns, sql=sql), self.assertRaises(package.Blocked):
                copy.transformation_map(contract, specs)
        contract['transformations'][0].update(columns=['amount'], oracle_sql='SELECT id,amount*2 AS amount FROM public.t')
        self.assertIn('public.t', copy.transformation_map(contract, specs))

    def test_row_oracle_rejects_incomplete_columns_and_preserves_duplicates(self):
        with patch.object(copy, 'value', return_value=['{"id": 1}']):
            with self.assertRaises(package.Blocked):
                copy.rows('copy', 'db', 'SELECT id FROM t', ['id', 'amount'])
        with patch.object(copy, 'value', return_value=['{"id": 1}', '{"id": 1}']):
            self.assertEqual(copy.rows('copy', 'db', 'SELECT id FROM t', ['id'])['rows'], 2)

    @staticmethod
    def pg_info(dump):
        return {'Id': 'a' * 64, 'Name': '/own', 'Image': copy.PG_IMAGE,
                'Config': {'Labels': {'crm-rel-001-owner': 'owner'}},
                'HostConfig': {'NetworkMode': 'none', 'PortBindings': {}, 'Privileged': False,
                               'Binds': [str(dump) + ':/backup/database.dump:ro']},
                'Mounts': [{'Type': 'bind', 'Source': str(dump), 'Destination': '/backup/database.dump', 'RW': False},
                           {'Type': 'volume', 'Source': '/private-owned-pg', 'Destination': '/var/lib/postgresql/data'}]}

    def test_pg_guard_refuses_production_volume_and_wrong_owner(self):
        dump = Path('/private/database.dump')
        info = self.pg_info(dump)
        with patch.object(copy, 'inspect', return_value=info):
            with self.assertRaisesRegex(package.Blocked, 'PRODUCTION_VOLUME_SHARED'):
                copy.owned('a' * 64, 'own', 'owner', dump, {'/private-owned-pg'})
            with self.assertRaisesRegex(package.Blocked, 'COPY_IDENTITY'):
                copy.owned('a' * 64, 'own', 'other', dump, set())

    def test_cleanup_adopts_partial_creation_only_after_identity_guard(self):
        dump = Path('/private/database.dump')
        found = subprocess.CompletedProcess([], 0, json.dumps([{'Id': 'a' * 64}]).encode(), b'')
        with patch.object(copy.subprocess, 'run', return_value=found), \
                patch.object(copy, 'owned', side_effect=package.Blocked('COPY_IDENTITY')), \
                patch.object(copy, 'run') as delete:
            with self.assertRaises(package.Blocked):
                copy.cleanup({'own': None}, 'owner', dump, set())
            delete.assert_not_called()

    def test_cleanup_failure_does_not_skip_other_owned_resource(self):
        absent = subprocess.CompletedProcess([], 1, b'[]', b'error: no such object')
        with patch.object(copy, 'owned', side_effect=[package.Blocked('COPY_IDENTITY'), None]), \
                patch.object(copy.subprocess, 'run', return_value=absent), \
                patch.object(copy, 'run') as delete:
            with self.assertRaisesRegex(package.Blocked, 'COPY_CLEANUP_UNCONFIRMED'):
                copy.cleanup({'one': 'a' * 64, 'two': 'b' * 64}, 'owner', Path('/dump'), set())
            delete.assert_called_once_with(['docker', 'rm', '-f', '-v', 'b' * 64])

    def test_probe_cleanup_refuses_unlabelled_container(self):
        found = subprocess.CompletedProcess([], 0, json.dumps([{
            'Name': '/own', 'Image': 'sha256:' + 'a' * 64, 'Config': {'Labels': {}}}]).encode(), b'')
        with patch.object(package.subprocess, 'run', return_value=found), patch.object(package, 'run') as delete:
            with self.assertRaises(package.Blocked):
                package.remove_probe('own', 'sha256:' + 'a' * 64, 'none')
            delete.assert_not_called()

    def exercise_rehearsal(self, *, fail_upgrade=False, baseline_failure=False, cleanup_failure=False,
                           interrupt=False, interrupt_cleanup=False, baseline_drift=False):
        events = []
        with fixtures() as directory:
            base = Path(directory)
            manifest, contract, baseline_path = (base / name for name in ('manifest', 'contract', 'baseline'))
            manifest.write_text('{}')
            contract.write_text('{}')
            baseline = {'schema': ['0116'], 'app_id': 'live-app', 'app_image': 'live-image',
                        'pg_id': 'live-pg', 'runtime_sha256': package.digest({})}
            baseline_path.write_text(json.dumps(baseline))
            args = argparse.Namespace(output=base / 'private-new', manifest=manifest, data_contract=contract,
                baseline=baseline_path, manifest_sha256=package.file_sha(manifest),
                data_contract_sha256=package.file_sha(contract), baseline_sha256=package.file_sha(baseline_path),
                image='sha256:' + 'c' * 64)

            def create(name, owner, dump, state, mounts, output):
                identity = 'first' if name.endswith('-upgrade') else 'second'
                events.append('create-' + identity)
                state[name] = identity
                return identity

            def execute(argv, **kwargs):
                kwargs['stdout'].write(b'PGDMP fixture')
                return subprocess.CompletedProcess(argv, 0, b'', b'')

            handlers = {}

            def upgrade(*unused, **kwargs):
                events.append('upgrade')
                if interrupt:
                    handlers[copy.signal.SIGTERM](copy.signal.SIGTERM, None)
                if fail_upgrade:
                    raise package.Blocked('UPGRADE_FAILED' if fail_upgrade is True else fail_upgrade)

            def current_schema(container, database):
                return [package.HEAD] if database == 'aios_copy' and 'upgrade' in events else ['0116']

            def inspect_live(name):
                if name == 'aios-app-1' and 'cleanup' in events:
                    events.append('baseline-after-cleanup')
                    if baseline_failure:
                        raise package.Blocked('FINAL_BASELINE_UNAVAILABLE')
                return {'Id': baseline['app_id' if name == 'aios-app-1' else 'pg_id'],
                        'Image': baseline['app_image'] if name == 'aios-app-1' else copy.PG_IMAGE,
                        'Mounts': [], 'State': {'Running': not (baseline_drift and 'cleanup' in events)}}

            def cleanup(*unused):
                events.append('cleanup')
                if interrupt_cleanup:
                    handlers[copy.signal.SIGTERM](copy.signal.SIGTERM, None)
                    events.append('cleanup-continued')
                if cleanup_failure:
                    raise package.Blocked('COPY_CLEANUP_UNCONFIRMED')

            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(copy.signal, 'getsignal', return_value=copy.signal.SIG_DFL))
                stack.enter_context(patch.object(copy.signal, 'signal', side_effect=lambda sig, handler: handlers.__setitem__(sig, handler)))
                for name, replacement in (
                    ('SERVER_ROOT', base), ('verify_image', lambda *a, **kw: {'status': 'verified'}),
                    ('inspect', inspect_live),
                    ('projection', lambda info: {}), ('schema', current_schema), ('create_copy', create),
                    ('restore', lambda container, db: events.append('restore-' + container + '-' + db)),
                    ('specs', lambda container: [{'schema': 'public', 'table': 't', 'columns': ['id'], 'numeric': [], 'keys': ['id']}]),
                    ('transformation_map', lambda *a: {}), ('snapshot', lambda *a: {'public.t': {'rows': 1, 'sha256': 'fixture'}}),
                    ('unchanged_columns', lambda *a: {}), ('links', lambda *a: {'fk': ['0']}),
                    ('probe', upgrade), ('run', lambda *a, **k: b'archive fixture'),
                    ('cleanup', cleanup)):
                    stack.enter_context(patch.object(copy, name, replacement))
                stack.enter_context(patch.object(copy.os, 'geteuid', return_value=0, create=True))
                stack.enter_context(patch.object(copy.socket, 'gethostname', return_value='localhost.localdomain'))
                stack.enter_context(patch.object(copy.subprocess, 'run', side_effect=execute))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                exit_code = copy.rehearsal(args)
            receipt = json.loads((args.output / 'receipt.json').read_text())
            self.assertTrue(handlers)
            self.assertTrue(all(handler == copy.signal.SIG_DFL for handler in handlers.values()))
        return exit_code, receipt, events

    def test_separate_restore_happens_after_two_real_upgrade_calls(self):
        code, receipt, events = self.exercise_rehearsal()
        self.assertEqual(code, 0)
        self.assertEqual(receipt['status'], 'FRESH_COPY_UPGRADE_AND_SEPARATE_RESTORE_PASS')
        self.assertEqual(events[:events.index('create-second')].count('upgrade'), 2)
        self.assertGreater(events.index('restore-second-aios_before'), events.index('create-second'))
        self.assertEqual(events[-1], 'baseline-after-cleanup')
        self.assertTrue(receipt['live_baseline_unchanged'])
        self.assertFalse(receipt['release_ready'])

    def test_upgrade_failure_is_nonzero_and_cleanup_receipt_is_honest(self):
        code, receipt, events = self.exercise_rehearsal(fail_upgrade=True)
        self.assertEqual(code, 1)
        self.assertEqual(receipt['status'], 'ISOLATED_REHEARSAL_FAILED')
        self.assertNotIn('create-second', events)
        self.assertEqual(events[-1], 'baseline-after-cleanup')
        self.assertTrue(receipt['live_baseline_unchanged'])
        self.assertTrue(receipt['owned_resources_removed'])

    def test_probe_cleanup_uncertainty_is_not_hidden_by_successful_pg_cleanup(self):
        code, receipt, events = self.exercise_rehearsal(fail_upgrade='PROBE_CLEANUP_UNCONFIRMED')
        self.assertEqual(code, 1)
        self.assertEqual(receipt['status'], 'OWNED_CLEANUP_UNCONFIRMED')
        self.assertFalse(receipt['owned_resources_removed'])
        self.assertEqual(events[-1], 'baseline-after-cleanup')
        self.assertTrue(receipt['live_baseline_unchanged'])


    def test_successful_remove_requires_fresh_absence_for_pg_and_probe(self):
        absent = subprocess.CompletedProcess([], 1, b'[]', b'error: no such object')
        present = subprocess.CompletedProcess([], 0, b'[{}]', b'')
        unknown = subprocess.CompletedProcess([], 1, b'[]', b'permission denied')
        mixed = subprocess.CompletedProcess([], 1, b'[]', b'error: no such object\npermission denied')
        for observed in (absent, present, unknown, mixed, subprocess.TimeoutExpired('docker', 30)):
            ok = observed is absent
            with self.subTest(kind=repr(observed)), fixtures() as directory:
                path, info = self.abandoned_probe(Path(directory))
                before = subprocess.CompletedProcess([], 0, json.dumps([info]).encode(), b'')
                with patch.object(package.subprocess, 'run', side_effect=[before, observed]) as readback, \
                        patch.object(package, 'run') as remove:
                    if ok:
                        self.assertEqual(package.remove_probe(info['Name'][1:], info['Image'], 'none'), info['Id'])
                    else:
                        with self.assertRaises((package.Blocked, subprocess.TimeoutExpired)):
                            package.remove_probe(info['Name'][1:], info['Image'], 'none')
                    remove.assert_called_once_with(['docker', 'rm', '-f', '-v', info['Id']])
                    self.assertEqual(readback.call_count, 2)
                    self.assertEqual(readback.call_args.args[0], ['docker', 'inspect', info['Name'][1:]])
                with patch.object(copy, 'owned'), patch.object(copy, 'run') as remove, \
                        patch.object(copy.subprocess, 'run', side_effect=[observed]) as readback:
                    if ok:
                        copy.cleanup({'own': 'b' * 64}, 'owner', Path('/dump'), set())
                    else:
                        with self.assertRaisesRegex(package.Blocked, 'COPY_CLEANUP_UNCONFIRMED'):
                            copy.cleanup({'own': 'b' * 64}, 'owner', Path('/dump'), set())
                    remove.assert_called_once_with(['docker', 'rm', '-f', '-v', 'b' * 64])
                    readback.assert_called_once_with(['docker', 'inspect', 'own'], capture_output=True, timeout=30)

    def test_final_baseline_uncertainty_cannot_pass_or_hide_original_failure(self):
        for failure in (False, True):
            with self.subTest(upgrade_failed=failure):
                code, receipt, events = self.exercise_rehearsal(fail_upgrade=failure, baseline_failure=True)
                self.assertEqual(code, 1)
                self.assertEqual(receipt['status'], 'LIVE_BASELINE_UNCONFIRMED')
                self.assertFalse(receipt['live_baseline_unchanged'])
                self.assertTrue(receipt['owned_resources_removed'])
                self.assertEqual(receipt['baseline_safe_code'], 'FINAL_BASELINE_UNAVAILABLE')
                self.assertEqual(events[-1], 'baseline-after-cleanup')
                if failure:
                    self.assertEqual(receipt['safe_code'], 'UPGRADE_FAILED')

    def test_cleanup_failure_still_checks_final_live_baseline(self):
        code, receipt, events = self.exercise_rehearsal(cleanup_failure=True, baseline_failure=True)
        self.assertEqual(code, 1)
        self.assertEqual(receipt['status'], 'OWNED_CLEANUP_UNCONFIRMED')
        self.assertFalse(receipt['owned_resources_removed'])
        self.assertFalse(receipt['live_baseline_unchanged'])
        self.assertEqual(receipt['cleanup_safe_code'], 'COPY_CLEANUP_UNCONFIRMED')
        self.assertEqual(receipt['baseline_safe_code'], 'FINAL_BASELINE_UNAVAILABLE')
        self.assertEqual(events[-1], 'baseline-after-cleanup')

    def test_termination_enters_cleanup_and_handlers_restore(self):
        code, receipt, events = self.exercise_rehearsal(interrupt=True, interrupt_cleanup=True)
        self.assertEqual(code, 1)
        self.assertEqual(receipt['safe_code'], 'REHEARSAL_INTERRUPTED')
        self.assertEqual(receipt['status'], 'ISOLATED_REHEARSAL_FAILED')
        self.assertTrue(receipt['owned_resources_removed'])
        self.assertTrue(receipt['live_baseline_unchanged'])
        self.assertNotIn('create-second', events)
        self.assertEqual(events[-3:], ['cleanup', 'cleanup-continued', 'baseline-after-cleanup'])

    def test_saved_handlers_restore_when_handler_installation_fails(self):
        # Preflight only; no owned output/container can be created before installation.
        with fixtures() as directory:
            base = Path(directory)
            for name, body in (('manifest', '{}'), ('contract', '{}'), ('baseline', json.dumps({
                    'schema': ['0116'], 'app_id': 'app', 'app_image': 'image',
                    'pg_id': 'pg', 'runtime_sha256': package.digest({})}))):
                (base / name).write_text(body)
            args = argparse.Namespace(output=base / 'new', manifest=base / 'manifest',
                data_contract=base / 'contract', baseline=base / 'baseline',
                manifest_sha256=package.file_sha(base / 'manifest'),
                data_contract_sha256=package.file_sha(base / 'contract'),
                baseline_sha256=package.file_sha(base / 'baseline'), image='sha256:' + 'a' * 64)
            handlers = {}
            calls = 0
            def install(sig, handler):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise ValueError('handler install fixture')
                handlers[sig] = handler
            with patch.object(copy, 'SERVER_ROOT', base), \
                    patch.object(copy.os, 'geteuid', return_value=0, create=True), \
                    patch.object(copy.socket, 'gethostname', return_value='localhost.localdomain'), \
                    patch.object(copy, 'inspect', side_effect=[{'Id': 'app', 'Image': 'image', 'Mounts': [], 'State': {'Running': True}},
                        {'Id': 'pg', 'Image': copy.PG_IMAGE, 'Mounts': [], 'State': {'Running': True}}]), \
                    patch.object(copy, 'projection', return_value={}), \
                    patch.object(copy, 'schema', return_value=['0116']), \
                    patch.object(copy.signal, 'getsignal', return_value=copy.signal.SIG_DFL), \
                    patch.object(copy.signal, 'signal', side_effect=install), \
                    patch.object(copy, 'protected_new_directory') as create:
                with self.assertRaises(ValueError):
                    copy.rehearsal(args)
                create.assert_not_called()
            self.assertTrue(all(handler == copy.signal.SIG_DFL for handler in handlers.values()))


    def test_stopped_live_container_after_cleanup_is_real_baseline_drift(self):
        code, receipt, events = self.exercise_rehearsal(baseline_drift=True)
        self.assertEqual(code, 1)
        self.assertEqual(receipt['status'], 'LIVE_BASELINE_UNCONFIRMED')
        self.assertEqual(receipt['baseline_safe_code'], 'LIVE_CHANGED_EXTERNALLY')
        self.assertFalse(receipt['live_baseline_unchanged'])
        self.assertEqual(events[-1], 'baseline-after-cleanup')


class IntakeQuiescence(unittest.TestCase):
    """Local component controls; kernel flock and all systemctl effects are mocked."""

    @staticmethod
    def states(*, timers_active=False, service_alive=False, job=False):
        return [{'unit': unit, 'definitionSHA256': package.digest({'fixture': unit}),
                 'active': 'active' if (timers_active and unit in package.INTAKE_TIMERS) or
                           (service_alive and unit in package.INTAKE_SERVICES) else 'inactive',
                 'sub': 'waiting' if timers_active and unit in package.INTAKE_TIMERS else
                        'running' if service_alive and unit in package.INTAKE_SERVICES else 'dead',
                 'jobPending': job, 'processesPresent': service_alive and unit in package.INTAKE_SERVICES}
                for unit in package.INTAKE_UNITS]

    @contextlib.contextmanager
    def prepared(self, batches=None):
        with fixtures() as base:
            root = Path(base)
            private = root / 'state'
            private.mkdir(mode=0o755 if os.name == 'nt' else 0o700)
            lock = root / 'global.lock'
            lock.touch()
            fd = os.open(lock, os.O_RDWR)
            clock = [0.0]
            batches = batches or [self.states(timers_active=True), self.states()]
            reads = [0]
            def unit_state(unit, *, timeout):
                batch = min(reads[0] // 4, len(batches)-1)
                reads[0] += 1
                return dict(next(x for x in batches[batch] if x['unit'] == unit))
            flock = Mock()
            native = SimpleNamespace(flock=flock, LOCK_EX=2, LOCK_NB=4)
            try:
                with patch.dict(sys.modules, {'fcntl': native}), \
                        patch.object(package.sys, 'platform', 'linux'), \
                        patch.object(package, 'RELEASE_LOCK', lock), \
                        patch.object(package, 'intake_unit', side_effect=unit_state) as observed, \
                        patch.object(package, 'run', return_value=b'') as command, \
                        patch.object(package.time, 'monotonic', side_effect=lambda: clock[0]), \
                        patch.object(package.time, 'sleep', side_effect=lambda x: clock.__setitem__(0, clock[0]+x)) as sleep:
                    yield SimpleNamespace(path=private/'intake.json', fd=fd, flock=flock,
                                          expected={x['unit']: x['definitionSHA256'] for x in self.states()},
                                          command=command, observed=observed, sleep=sleep, root=root,
                                          clock=clock)
            finally:
                os.close(fd)

    def test_observed_drain_is_only_intake_component_and_record_precedes_stop(self):
        with self.prepared() as case:
            def stop(argv, **kwargs):
                durable = json.loads(case.path.read_text())
                self.assertEqual(durable['status'], 'TIMER_STOP_ATTEMPTED_DRAIN_UNKNOWN')
                self.assertTrue(durable['timerStopAttempted'])
                self.assertFalse(durable['fullFreezeAccepted'])
                self.assertEqual(argv, ['systemctl', 'stop', '--no-ask-password', '--job-mode=fail',
                                       'crm-admin-mail-stage.timer', 'crm-mottor-intake.timer'])
                return b''
            case.command.side_effect = stop
            result = package.quiesce_intake(case.path, case.expected, lease_fd=case.fd)
            self.assertEqual(result['status'], 'INTAKE_TIMERS_STOPPED_SERVICES_DRAINED')
            self.assertFalse(result['queueMutationAttempted'])
            self.assertFalse(result['releaseReady'])
            self.assertFalse(result['fullFreezeAccepted'])
            self.assertEqual(json.loads(case.path.read_text()), result)
            case.command.assert_called_once()
            case.flock.assert_called_once_with(case.fd, 6)

    def test_inflight_service_is_observed_to_completion_without_stop_or_kill(self):
        with self.prepared([self.states(timers_active=True, service_alive=True),
                            self.states(service_alive=True), self.states()]) as case:
            result = package.quiesce_intake(case.path, case.expected, lease_fd=case.fd)
            self.assertEqual(result['status'], 'INTAKE_TIMERS_STOPPED_SERVICES_DRAINED')
            self.assertEqual(case.observed.call_count, 12)
            self.assertEqual([x.args[0] for x in case.observed.call_args_list[-4:]],
                             list(package.INTAKE_SERVICES + package.INTAKE_TIMERS))
            case.sleep.assert_called_once_with(0.25)
            self.assertEqual(case.command.call_count, 1)

    def test_failed_service_with_no_process_or_job_is_drained(self):
        after = self.states()
        after[-1].update(active='failed', sub='failed')
        with self.prepared([self.states(timers_active=True), after]) as case:
            self.assertEqual(package.quiesce_intake(case.path, case.expected, lease_fd=case.fd)
                             ['status'], 'INTAKE_TIMERS_STOPPED_SERVICES_DRAINED')

    def test_identity_mismatch_prevents_record_and_timer_mutation(self):
        with self.prepared() as case:
            case.expected[package.INTAKE_SERVICES[0]] = '0'*64
            with self.assertRaisesRegex(package.Blocked, 'INTAKE_UNIT_DEFINITION_DRIFT'):
                package.quiesce_intake(case.path, case.expected, lease_fd=case.fd)
            case.command.assert_not_called()
            self.assertFalse(case.path.exists())

    def test_exclusive_record_reservation_refuses_racing_foreign_record(self):
        with self.prepared() as case:
            original = case.observed.side_effect
            def observe(unit, **kwargs):
                result = original(unit, **kwargs)
                if unit == package.INTAKE_SERVICES[-1]:
                    case.path.write_text('foreign-record')
                return result
            case.observed.side_effect = observe
            with self.assertRaises(FileExistsError):
                package.quiesce_intake(case.path, case.expected, lease_fd=case.fd)
            self.assertEqual(case.path.read_text(), 'foreign-record')
            case.command.assert_not_called()

    def test_existing_or_interrupted_empty_record_refuses_retry(self):
        with self.prepared() as case:
            case.path.touch()
            with self.assertRaisesRegex(package.Blocked, 'INTAKE_RECORD_EXISTS_NO_RETRY'):
                package.quiesce_intake(case.path, case.expected, lease_fd=case.fd)
            case.command.assert_not_called()
            case.observed.assert_not_called()

    def test_wrong_global_descriptor_and_competing_lease_refuse_before_observation(self):
        with self.prepared() as case:
            wrong = os.open(case.path.parent/'wrong.lock', os.O_RDWR | os.O_CREAT, 0o600)
            try:
                with self.assertRaisesRegex(package.Blocked, 'INTAKE_GLOBAL_LEASE'):
                    package.quiesce_intake(case.path, case.expected, lease_fd=wrong)
            finally:
                os.close(wrong)
            case.flock.side_effect = BlockingIOError()
            with self.assertRaisesRegex(package.Blocked, 'ANOTHER_RELEASE_RUNNING'):
                package.quiesce_intake(case.path, case.expected, lease_fd=case.fd)
            case.command.assert_not_called()
            case.observed.assert_not_called()

    def test_lost_stop_reply_retains_unknown_and_never_reopens_or_retries(self):
        with self.prepared() as case:
            case.command.side_effect = package.Blocked('COMMAND_UNAVAILABLE_OR_TIMEOUT')
            with self.assertRaisesRegex(package.Blocked, 'COMMAND_UNAVAILABLE_OR_TIMEOUT'):
                package.quiesce_intake(case.path, case.expected, lease_fd=case.fd)
            receipt = json.loads(case.path.read_text())
            self.assertEqual(receipt['status'], 'INTAKE_QUIESCENCE_UNKNOWN_NO_REOPEN')
            self.assertTrue(receipt['timerStopAttempted'])
            with self.assertRaisesRegex(package.Blocked, 'INTAKE_RECORD_EXISTS_NO_RETRY'):
                package.quiesce_intake(case.path, case.expected, lease_fd=case.fd)
            self.assertEqual(case.command.call_count, 1)

    def test_pending_jobs_active_timers_processes_and_unknown_states_never_pass(self):
        for change in ({'jobPending': True}, {'processesPresent': True},
                       {'active': 'active', 'sub': 'exited'}, {'active': 'UNKNOWN', 'sub': 'UNKNOWN'}):
            with self.subTest(change=change):
                after = self.states()
                after[-1].update(change)
                with self.prepared([self.states(timers_active=True), after]) as case:
                    with self.assertRaisesRegex(package.Blocked, 'INTAKE_DRAIN_TIMEOUT'):
                        package.quiesce_intake(case.path, case.expected, lease_fd=case.fd, timeout=1)
                    self.assertEqual(json.loads(case.path.read_text())['status'],
                                     'INTAKE_QUIESCENCE_UNKNOWN_NO_REOPEN')
                    self.assertEqual(case.command.call_count, 1)
        with self.prepared([self.states(timers_active=True)]) as case:
            with self.assertRaisesRegex(package.Blocked, 'INTAKE_DRAIN_TIMEOUT'):
                package.quiesce_intake(case.path, case.expected, lease_fd=case.fd, timeout=1)

    def test_definition_change_during_drain_preserves_unknown(self):
        after = self.states()
        after[-1]['definitionSHA256'] = '1'*64
        with self.prepared([self.states(timers_active=True), after]) as case:
            with self.assertRaisesRegex(package.Blocked, 'INTAKE_UNIT_DEFINITION_DRIFT'):
                package.quiesce_intake(case.path, case.expected, lease_fd=case.fd)
            self.assertEqual(json.loads(case.path.read_text())['status'],
                             'INTAKE_QUIESCENCE_UNKNOWN_NO_REOPEN')

    def test_interruption_keeps_durable_unknown_without_service_signal(self):
        with self.prepared() as case:
            case.command.side_effect = KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                package.quiesce_intake(case.path, case.expected, lease_fd=case.fd)
            self.assertEqual(json.loads(case.path.read_text())['errorType'], 'KeyboardInterrupt')
            self.assertEqual(case.command.call_count, 1)

    @contextlib.contextmanager
    def unit_output(self, unit):
        body = b'[Unit]\nDescription=local fixture\n'
        file_name = '/etc/systemd/system/' + unit
        props = {'Id': unit, 'LoadState': 'loaded', 'NeedDaemonReload': 'no',
                 'FragmentPath': file_name, 'DropInPaths': '', 'PropagatesStopTo': '',
                 'ConsistsOf': '', 'BoundBy': '', 'OnSuccess': '', 'OnFailure': '',
                 'RequiredBy': '', 'RequisiteOf': '', 'UpheldBy': '',
                 'ActiveState': 'inactive', 'SubState': 'dead', 'Job': ''}
        if unit in package.INTAKE_SERVICES:
            props.update(Type='oneshot', Restart='no', RemainAfterExit='no',
                         StopWhenUnneeded='no', MainPID='0', ControlPID='0', ControlGroup='')
        else:
            props['Triggers'] = unit.removesuffix('.timer') + '.service'
        class UnitFile(PurePosixPath):
            def resolve(self, strict=False): return self
            def is_file(self): return str(self) == file_name
            def stat(self): return SimpleNamespace(st_size=len(body))
            def read_bytes(self): return body
        def show(*args, **kwargs):
            return ''.join(k+'='+v+'\n' for k, v in props.items()).encode()
        with patch.object(package, 'Path', UnitFile), patch.object(package, 'run', side_effect=show):
            yield props

    def test_unit_metadata_binds_files_and_does_not_export_raw_properties(self):
        for unit in package.INTAKE_UNITS:
            with self.subTest(unit=unit), self.unit_output(unit) as props:
                result = package.intake_unit(unit, timeout=3)
                self.assertEqual(set(result), {'unit', 'definitionSHA256', 'active', 'sub',
                                               'jobPending', 'processesPresent'})
                self.assertEqual(len(result['definitionSHA256']), 64)
                self.assertFalse(result['processesPresent'])
                props['OnFailure'] = 'other.service'
                if unit in package.INTAKE_TIMERS:
                    with self.assertRaisesRegex(package.Blocked, 'INTAKE_STOP_CASCADE'):
                        package.intake_unit(unit, timeout=3)
                else:
                    with self.assertRaisesRegex(package.Blocked, 'INTAKE_SERVICE_LIFECYCLE'):
                        package.intake_unit(unit, timeout=3)

    def test_stop_cascade_and_auto_stopping_service_refuse(self):
        for name in ('PropagatesStopTo', 'ConsistsOf', 'BoundBy', 'RequiredBy', 'RequisiteOf',
                     'UpheldBy', 'OnSuccess', 'OnFailure'):
            with self.subTest(name=name), self.unit_output(package.INTAKE_TIMERS[0]) as props:
                props[name] = 'other.service'
                with self.assertRaisesRegex(package.Blocked, 'INTAKE_STOP_CASCADE'):
                    package.intake_unit(package.INTAKE_TIMERS[0], timeout=3)
        with self.unit_output(package.INTAKE_SERVICES[0]) as props:
            props['StopWhenUnneeded'] = 'yes'
            with self.assertRaisesRegex(package.Blocked, 'INTAKE_SERVICE_LIFECYCLE'):
                package.intake_unit(package.INTAKE_SERVICES[0], timeout=3)

    def test_empty_job_is_systemd_no_job_and_live_cgroup_is_not_drained(self):
        with self.unit_output(package.INTAKE_SERVICES[0]) as props:
            self.assertFalse(package.intake_unit(package.INTAKE_SERVICES[0], timeout=3)['jobPending'])
            props['Job'] = '42'
            props['ControlGroup'] = '/system.slice/fixture.service'
            result = package.intake_unit(package.INTAKE_SERVICES[0], timeout=3)
            self.assertTrue(result['jobPending'])
            self.assertTrue(result['processesPresent'])

    def test_service_completion_hooks_refuse_before_any_timer_effect(self):
        reader = package.intake_unit
        for name in ('OnSuccess', 'OnFailure'):
            with self.subTest(name=name), self.prepared() as case, \
                    self.unit_output(package.INTAKE_SERVICES[0]) as props:
                props[name] = package.INTAKE_TIMERS[0]
                case.observed.side_effect = reader
                with self.assertRaisesRegex(package.Blocked, 'INTAKE_SERVICE_LIFECYCLE'):
                    package.quiesce_intake(case.path, case.expected, lease_fd=case.fd)
                case.command.assert_not_called()
                self.assertFalse(case.path.exists())

    def test_terminal_snapshot_past_deadline_is_unknown_not_success(self):
        with self.prepared() as case:
            original = case.observed.side_effect
            calls = [0]
            def late(unit, **kwargs):
                result = original(unit, **kwargs)
                calls[0] += 1
                if calls[0] == 8:
                    case.clock[0] = 2
                return result
            case.observed.side_effect = late
            with self.assertRaisesRegex(package.Blocked, 'INTAKE_DRAIN_TIMEOUT'):
                package.quiesce_intake(case.path, case.expected, lease_fd=case.fd, timeout=1)
            self.assertEqual(json.loads(case.path.read_text())['status'],
                             'INTAKE_QUIESCENCE_UNKNOWN_NO_REOPEN')
            case.command.assert_called_once()
            case.sleep.assert_not_called()

    def test_unknown_malformed_unit_properties_and_path_refuse(self):
        for field, value, error in (('NeedDaemonReload', 'yes', 'INTAKE_UNIT_NOT_CURRENT'),
                                    ('FragmentPath', '/etc/secret', 'INTAKE_UNIT_FILE_SCOPE'),
                                    ('MainPID', 'unknown', 'INTAKE_PID_UNKNOWN'),
                                    ('Job', '0 /unknown', 'INTAKE_STATE_UNKNOWN'),
                                    ('ActiveState', 'new-state', 'INTAKE_STATE_UNKNOWN')):
            with self.subTest(field=field), self.unit_output(package.INTAKE_SERVICES[0]) as props:
                props[field] = value
                with self.assertRaisesRegex(package.Blocked, error):
                    package.intake_unit(package.INTAKE_SERVICES[0], timeout=3)
        with self.unit_output(package.INTAKE_SERVICES[0]) as props:
            del props['Job']
            with self.assertRaisesRegex(package.Blocked, 'INTAKE_UNIT_PROPERTIES'):
                package.intake_unit(package.INTAKE_SERVICES[0], timeout=3)


class ApplicationQuiescence(unittest.TestCase):
    """Public fixtures only; Docker and kernel flock effects are mocked."""

    @contextlib.contextmanager
    def prepared(self):
        with fixtures() as base:
            root = Path(base)
            private = root / 'state'
            private.mkdir(mode=0o755 if os.name == 'nt' else 0o700)
            lock = root / 'global.lock'
            lock.touch()
            fd = os.open(lock, os.O_RDWR)
            clock = [0.0]
            before = {'Id': 'a'*64, 'Name': '/aios-app-1', 'Image': 'sha256:'+'b'*64,
                      'State': {'Running': True, 'Restarting': False, 'Paused': False, 'Dead': False},
                      'Config': {'Env': ['PRIVATE_FIXTURE=not-exported'], 'Labels': {}},
                      'HostConfig': {'RestartPolicy': {'Name': 'no', 'MaximumRetryCount': 0},
                                     'Dns': ['fixture-dns']},
                      'Mounts': [], 'NetworkSettings': {'Networks': {'fixture-network': {}}}}
            after = json.loads(json.dumps(before))
            after['State']['Running'] = False
            expected = {'id': before['Id'], 'image': before['Image'], 'running': True,
                        'restartPolicy': before['HostConfig']['RestartPolicy'].copy(),
                        'runtimeSHA256': package.digest(package.projection(before))}
            reads = [0]
            def respond(argv, **kwargs):
                if argv[:2] == ['docker', 'inspect']:
                    data = before if reads[0] == 0 else after
                    reads[0] += 1
                    return json.dumps([data]).encode()
                if argv[:2] == ['docker', 'stop']:
                    return b''
                raise AssertionError('Unexpected external command')
            native = SimpleNamespace(flock=Mock(), LOCK_EX=2, LOCK_NB=4)
            runner = Path(__file__).resolve().parents[5] / 'ops/belakb-deploy/deploy.py'
            try:
                with patch.dict(sys.modules, {'fcntl': native}), \
                        patch.object(package.sys, 'platform', 'linux'), \
                        patch.object(package, 'RELEASE_LOCK', lock), \
                        patch.object(package, 'APPLICATION_RUNNER', runner), \
                        patch.object(package, 'run', side_effect=respond) as command, \
                        patch.object(package.time, 'monotonic', side_effect=lambda: clock[0]):
                    yield SimpleNamespace(path=private/'app.json', fd=fd, flock=native.flock,
                                          root=root, clock=clock, before=before, after=after,
                                          expected=expected, command=command, respond=respond)
            finally:
                os.close(fd)

    def test_durable_attempt_precedes_single_exact_stop_and_private_readback(self):
        with self.prepared() as c:
            def respond(argv, **kwargs):
                if argv[:2] == ['docker', 'stop']:
                    record = json.loads(c.path.read_bytes())
                    self.assertEqual(record['status'], 'APPLICATION_STOP_ATTEMPTED_STATE_UNKNOWN')
                    self.assertTrue(record['applicationStopAttempted'])
                    self.assertFalse(record['fullFreezeAccepted'])
                    self.assertEqual(argv, ['docker', 'stop', '--time', '5', 'a'*64])
                    self.assertGreater(kwargs['timeout'], 5)
                    self.assertLessEqual(kwargs['timeout'], 8)
                return c.respond(argv, **kwargs)
            c.command.side_effect = respond
            result = package.quiesce_application(c.path, c.expected, lease_fd=c.fd)
            self.assertEqual(result['status'], 'APPLICATION_STOPPED_COMPONENT_ONLY')
            self.assertFalse(result['application']['running'])
            self.assertFalse(result['releaseReady'])
            self.assertFalse(result['guardMutationAttempted'])
            self.assertEqual(json.loads(c.path.read_bytes()), result)
            self.assertNotIn('PRIVATE_FIXTURE', c.path.read_text())
            self.assertNotIn('fixture-dns', c.path.read_text())
            self.assertEqual([x.args[0] for x in c.command.call_args_list],
                             [['docker', 'inspect', 'aios-app-1'],
                              ['docker', 'stop', '--time', '5', 'a'*64],
                              ['docker', 'inspect', 'a'*64]])
            c.flock.assert_called_once_with(c.fd, 6)

    def test_wrong_baseline_or_name_state_refuses_before_durable_stop(self):
        for field in ('Id', 'Image', 'Dns', 'RestartPolicy', 'Name', 'Running', 'Paused'):
            with self.subTest(field=field), self.prepared() as c:
                if field == 'Dns':
                    c.before['HostConfig']['Dns'] = []
                elif field == 'RestartPolicy':
                    c.before['HostConfig'][field]['Name'] = 'always'
                elif field in ('Running', 'Paused'):
                    c.before['State'][field] = field == 'Paused'
                else:
                    c.before[field] = 'wrong'
                with self.assertRaises(package.Blocked):
                    package.quiesce_application(c.path, c.expected, lease_fd=c.fd)
                self.assertFalse(c.path.exists())
                self.assertEqual(c.command.call_count, 1)

    def test_caller_baseline_mutation_after_admission_cannot_redirect_stop(self):
        with self.prepared() as c:
            writer = package.write_probe_state
            def mutate_caller(path, record):
                writer(path, record)
                if record['applicationStopAttempted']:
                    c.expected.update(id='c'*64, image='sha256:'+'d'*64,
                                      runtimeSHA256='e'*64, running=False)
                    c.expected['restartPolicy']['Name'] = 'always'
            with patch.object(package, 'write_probe_state', side_effect=mutate_caller):
                result = package.quiesce_application(c.path, c.expected, lease_fd=c.fd)
            self.assertEqual(result['status'], 'APPLICATION_STOPPED_COMPONENT_ONLY')
            self.assertEqual(result['application']['id'], 'a'*64)
            self.assertEqual(result['application']['restartPolicy']['Name'], 'no')
            self.assertEqual([x.args[0] for x in c.command.call_args_list],
                             [['docker', 'inspect', 'aios-app-1'],
                              ['docker', 'stop', '--time', '5', 'a'*64],
                              ['docker', 'inspect', 'a'*64]])

    def test_arbitrary_target_invalid_baseline_timeout_platform_and_optimize_refuse(self):
        for change in ('target', 'running', 'restart', 'bool-retry', 'bad-id'):
            with self.subTest(change=change), self.prepared() as c:
                if change == 'target':
                    c.expected["target"] = "postgres"
                elif change == "running":
                    c.expected["running"] = 1
                elif change == "restart":
                    c.expected["restartPolicy"]["Name"] = "always"
                elif change == "bool-retry":
                    c.expected["restartPolicy"]["MaximumRetryCount"] = False
                else:
                    c.expected["id"] = "arbitrary"
                with self.assertRaisesRegex(package.Blocked, 'APPLICATION_BASELINE_BINDING'):
                    package.quiesce_application(c.path, c.expected, lease_fd=c.fd)
                c.command.assert_not_called()
        for timeout in (True, 0, 61, 1.5):
            with self.subTest(timeout=timeout), self.prepared() as c:
                with self.assertRaisesRegex(package.Blocked, 'APPLICATION_DEADLINE'):
                    package.quiesce_application(c.path, c.expected, lease_fd=c.fd, timeout=timeout)
                c.command.assert_not_called()
        for field, value in (('platform', 'win32'), ('flags', SimpleNamespace(optimize=1))):
            with self.subTest(field=field), self.prepared() as c, patch.object(package.sys, field, value):
                with self.assertRaisesRegex(package.Blocked, 'LINUX_NONOPTIMIZED_REQUIRED'):
                    package.quiesce_application(c.path, c.expected, lease_fd=c.fd)
                c.command.assert_not_called()

    def test_existing_empty_pending_or_raced_receipt_prevents_repeat(self):
        for kind in ('empty', 'pending', 'raced'):
            with self.subTest(kind=kind), self.prepared() as c:
                target = c.path.with_suffix('.pending') if kind == 'pending' else c.path
                if kind != "raced":
                    target.write_text("")
                else:
                    def respond(argv, **kwargs):
                        target.write_text('reservation-by-other-caller')
                        return c.respond(argv, **kwargs)
                    c.command.side_effect = respond
                with self.assertRaises((package.Blocked, FileExistsError)):
                    package.quiesce_application(c.path, c.expected, lease_fd=c.fd)
                self.assertEqual(target.read_text(), 'reservation-by-other-caller' if kind == 'raced' else '')
                self.assertFalse(any(x.args[0][:2] == ['docker', 'stop'] for x in c.command.call_args_list))

    def test_wrong_descriptor_or_competing_release_refuses_effects(self):
        for kind in ('bool', 'different-file', 'competing'):
            with self.subTest(kind=kind), self.prepared() as c:
                other = c.root / "other.lock"
                other.touch()
                other_fd = os.open(other, os.O_RDWR)
                try:
                    if kind == "competing":
                        c.flock.side_effect = BlockingIOError()
                    fd = True if kind == 'bool' else other_fd if kind == 'different-file' else c.fd
                    with self.assertRaises(package.Blocked):
                        package.quiesce_application(c.path, c.expected, lease_fd=fd)
                    c.command.assert_not_called()
                    self.assertFalse(c.path.exists())
                finally:
                    os.close(other_fd)

    def test_installed_primitive_seal_mismatch_refuses_before_observation(self):
        with self.prepared() as c, patch.object(package, 'APPLICATION_RUNNER_SHA', '0'*64):
            with self.assertRaisesRegex(package.Blocked, 'INSTALLED_RUNNER_CHANGED'):
                package.quiesce_application(c.path, c.expected, lease_fd=c.fd)
            c.command.assert_not_called()
            self.assertFalse(c.path.exists())

    def test_lost_reply_interrupt_or_late_stop_is_unknown_and_never_retried(self):
        for kind in ('lost', 'interrupt', 'late'):
            with self.subTest(kind=kind), self.prepared() as c:
                def respond(argv, **kwargs):
                    if argv[:2] == ['docker', 'stop']:
                        if kind == "lost":
                            raise package.Blocked("COMMAND_UNAVAILABLE_OR_TIMEOUT")
                        if kind == "interrupt":
                            raise KeyboardInterrupt()
                        c.clock[0] = 31
                    return c.respond(argv, **kwargs)
                c.command.side_effect = respond
                with self.assertRaises((package.Blocked, KeyboardInterrupt)):
                    package.quiesce_application(c.path, c.expected, lease_fd=c.fd)
                self.assertEqual(json.loads(c.path.read_bytes())['status'],
                                 'APPLICATION_QUIESCENCE_UNKNOWN_NO_REOPEN')
                self.assertEqual(c.command.call_count, 2)
                with self.assertRaisesRegex(package.Blocked, 'APPLICATION_RECORD_EXISTS_NO_RETRY'):
                    package.quiesce_application(c.path, c.expected, lease_fd=c.fd)
                self.assertEqual(c.command.call_count, 2)

    def test_late_before_or_after_observation_cannot_report_success(self):
        for phase in ('before', 'after'):
            with self.subTest(phase=phase), self.prepared() as c:
                def respond(argv, **kwargs):
                    result = c.respond(argv, **kwargs)
                    if argv[:2] == ['docker', 'inspect'] and (argv[-1] == 'aios-app-1') == (phase == 'before'):
                        c.clock[0] = 31
                    return result
                c.command.side_effect = respond
                with self.assertRaisesRegex(package.Blocked, 'APPLICATION_STOP_TIMEOUT'):
                    package.quiesce_application(c.path, c.expected, lease_fd=c.fd)
                if phase == 'before':
                    self.assertFalse(c.path.exists())
                else:
                    self.assertEqual(
                        json.loads(c.path.read_bytes())["status"],
                        "APPLICATION_QUIESCENCE_UNKNOWN_NO_REOPEN",
                    )

    def test_postread_same_stopped_identity_and_raw_config_are_required(self):
        for kind in ('running', 'id', 'image', 'dns', 'restart', 'name'):
            with self.subTest(kind=kind), self.prepared() as c:
                if kind == 'running':
                    c.after["State"]["Running"] = True
                elif kind == "id":
                    c.after["Id"] = "c" * 64
                elif kind == "image":
                    c.after["Image"] = "sha256:" + "c" * 64
                elif kind == "dns":
                    c.after["HostConfig"]["Dns"] = []
                elif kind == "restart":
                    c.after["HostConfig"]["RestartPolicy"]["Name"] = "always"
                else:
                    c.after["Name"] = "/another-app"
                with self.assertRaises(package.Blocked):
                    package.quiesce_application(c.path, c.expected, lease_fd=c.fd)
                self.assertEqual(json.loads(c.path.read_bytes())['status'],
                                 'APPLICATION_QUIESCENCE_UNKNOWN_NO_REOPEN')
                self.assertEqual(c.command.call_count, 3)

    def test_all_commands_share_deadline_and_small_budget_does_not_stop(self):
        with self.prepared() as c:
            def respond(argv, **kwargs):
                if argv[-1] == 'aios-app-1':
                    c.clock[0] = 1
                elif argv[:2] == ["docker", "stop"]:
                    c.clock[0] = 6
                else:
                    c.clock[0] = 9
                return c.respond(argv, **kwargs)
            c.command.side_effect = respond
            package.quiesce_application(c.path, c.expected, lease_fd=c.fd, timeout=10)
            self.assertEqual([x.kwargs['timeout'] for x in c.command.call_args_list], [5, 8, 4])
        with self.prepared() as c:
            with self.assertRaisesRegex(package.Blocked, 'APPLICATION_STOP_TIMEOUT'):
                package.quiesce_application(c.path, c.expected, lease_fd=c.fd, timeout=5)
            self.assertEqual(c.command.call_count, 1)
            self.assertEqual(json.loads(c.path.read_bytes())['status'],
                             'APPLICATION_QUIESCENCE_UNKNOWN_NO_REOPEN')

    def test_failed_attempt_record_write_cannot_issue_stop(self):
        with self.prepared() as c:
            writer = package.write_probe_state
            calls = [0]
            def fail_attempt(path, record):
                calls[0] += 1
                if calls[0] == 2:
                    raise OSError("fixture-persistence-error")
                writer(path, record)
            with patch.object(package, 'write_probe_state', side_effect=fail_attempt):
                with self.assertRaises(OSError):
                    package.quiesce_application(c.path, c.expected, lease_fd=c.fd)
            self.assertEqual(c.command.call_count, 1)
            self.assertEqual(json.loads(c.path.read_bytes())['status'],
                             'APPLICATION_QUIESCENCE_UNKNOWN_NO_REOPEN')


if __name__ == '__main__':
    unittest.main()
