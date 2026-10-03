"""Local guard/lifecycle tests only: Docker, PostgreSQL and Git export are mocked."""
import argparse
import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

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
            self.assertIn('FROM ' + package.RUNTIME, recipe)
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
                with patch.object(package.subprocess, 'run', return_value=found), \
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
        with patch.object(copy, 'owned', side_effect=[package.Blocked('COPY_IDENTITY'), None]), \
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

    def exercise_rehearsal(self, *, fail_upgrade=False):
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

            def upgrade(*unused, **kwargs):
                events.append('upgrade')
                if fail_upgrade:
                    raise package.Blocked('UPGRADE_FAILED' if fail_upgrade is True else fail_upgrade)

            def current_schema(container, database):
                return [package.HEAD] if database == 'aios_copy' and 'upgrade' in events else ['0116']

            with contextlib.ExitStack() as stack:
                for name, replacement in (
                    ('SERVER_ROOT', base), ('verify_image', lambda *a, **kw: {'status': 'verified'}),
                    ('inspect', lambda name: {'Id': baseline['app_id' if name == 'aios-app-1' else 'pg_id'],
                        'Image': baseline['app_image'] if name == 'aios-app-1' else copy.PG_IMAGE, 'Mounts': []}),
                    ('projection', lambda info: {}), ('schema', current_schema), ('create_copy', create),
                    ('restore', lambda container, db: events.append('restore-' + container + '-' + db)),
                    ('specs', lambda container: [{'schema': 'public', 'table': 't', 'columns': ['id'], 'numeric': [], 'keys': ['id']}]),
                    ('transformation_map', lambda *a: {}), ('snapshot', lambda *a: {'public.t': {'rows': 1, 'sha256': 'fixture'}}),
                    ('unchanged_columns', lambda *a: {}), ('links', lambda *a: {'fk': ['0']}),
                    ('probe', upgrade), ('run', lambda *a, **k: b'archive fixture'),
                    ('cleanup', lambda *a: events.append('cleanup'))):
                    stack.enter_context(patch.object(copy, name, replacement))
                stack.enter_context(patch.object(copy.os, 'geteuid', return_value=0, create=True))
                stack.enter_context(patch.object(copy.socket, 'gethostname', return_value='localhost.localdomain'))
                stack.enter_context(patch.object(copy.subprocess, 'run', side_effect=execute))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                exit_code = copy.rehearsal(args)
            receipt = json.loads((args.output / 'receipt.json').read_text())
        return exit_code, receipt, events

    def test_separate_restore_happens_after_two_real_upgrade_calls(self):
        code, receipt, events = self.exercise_rehearsal()
        self.assertEqual(code, 0)
        self.assertEqual(receipt['status'], 'FRESH_COPY_UPGRADE_AND_SEPARATE_RESTORE_PASS')
        self.assertEqual(events[:events.index('create-second')].count('upgrade'), 2)
        self.assertGreater(events.index('restore-second-aios_before'), events.index('create-second'))
        self.assertEqual(events[-1], 'cleanup')
        self.assertFalse(receipt['release_ready'])

    def test_upgrade_failure_is_nonzero_and_cleanup_receipt_is_honest(self):
        code, receipt, events = self.exercise_rehearsal(fail_upgrade=True)
        self.assertEqual(code, 1)
        self.assertEqual(receipt['status'], 'ISOLATED_REHEARSAL_FAILED')
        self.assertNotIn('create-second', events)
        self.assertEqual(events[-1], 'cleanup')
        self.assertTrue(receipt['owned_resources_removed'])

    def test_probe_cleanup_uncertainty_is_not_hidden_by_successful_pg_cleanup(self):
        code, receipt, events = self.exercise_rehearsal(fail_upgrade='PROBE_CLEANUP_UNCONFIRMED')
        self.assertEqual(code, 1)
        self.assertEqual(receipt['status'], 'OWNED_CLEANUP_UNCONFIRMED')
        self.assertFalse(receipt['owned_resources_removed'])
        self.assertEqual(events[-1], 'cleanup')


if __name__ == '__main__':
    unittest.main()
