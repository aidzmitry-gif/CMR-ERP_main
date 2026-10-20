"""Private Linux adapter for the existing catalogue QA kernel; no app imports."""
import base64
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ASSETS = {'G12KZ-backend.py', 'G12KZ-observer-fragment.py', 'G12KZ-pool.spec.cjs',
          'G12KZ-playwright.config.cjs', 'G12KZ-profile.json', 'G12LH-run-pool.py', 'G12LJ-kernel.py'}
FIELDS = {'stage', 'schema', 'sqlalchemy', 'aiosqlite', 'poolClass', 'size', 'maxOverflow',
          'active', 'out', 'in', 'anomalies', 'owners', 'subscribers'}
VERSION = re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,4}[a-zA-Z0-9.+-]{0,16}')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounded(value, minimum=0, maximum=1_000_000):
    assert type(value) is int and minimum <= value <= maximum


def numeric_stage(value):
    assert type(value) is dict and set(value) == FIELDS
    bounded(value['stage'], 1, 6)
    assert value['schema'] == 1 and type(value['schema']) is int
    for field in ('sqlalchemy', 'aiosqlite'):
        assert type(value[field]) is str and VERSION.fullmatch(value[field])
    assert (value['poolClass'], value['size'], value['maxOverflow']) == (1, 5, 10)
    for field in ('poolClass', 'size', 'maxOverflow', 'active', 'out', 'in', 'anomalies'):
        bounded(value[field])
    assert value['anomalies'] == 0 and value['out'] - value['in'] == value['active']
    owners = value['owners']
    assert type(owners) is list and len(owners) == 5
    for expected, row in enumerate(owners):
        assert type(row) is list and len(row) == 2 and type(row[0]) is int and row[0] == expected
        bounded(row[1])
    assert sum(row[1] for row in owners) == value['active']
    assert type(value['subscribers']) is list and len(value['subscribers']) == 2
    for count in value['subscribers']:
        bounded(count)
    # Roundtrip only after every key and leaf has passed the fixed allowlist.
    return json.loads(json.dumps(value))


def pool_attachments(attempt, expected_stages):
    stages = []
    dropped = 0
    attachments = attempt.get('attachments', [])
    assert type(attachments) is list and len(attachments) <= 16
    passed = attempt.get('status') == 'passed'
    for attachment in attachments:
        assert type(attachment) is dict
        name = attachment.get('name')
        if type(name) is not str or not re.fullmatch(r'pool-stage-[1-6]', name):
            assert not passed
            dropped += 1
            continue
        assert set(attachment) == {'name', 'contentType', 'body'}
        assert attachment['contentType'] == 'application/json'
        assert type(attachment['body']) is str and len(attachment['body']) <= 8192
        raw = base64.b64decode(attachment['body'], validate=True)
        assert len(raw) <= 4096
        stage = numeric_stage(json.loads(raw))
        assert name == f"pool-stage-{stage['stage']}" and stage['stage'] in expected_stages
        assert stage['stage'] not in {item['stage'] for item in stages}
        stages.append(stage)
    assert len(stages) <= 2
    if passed:
        assert [item['stage'] for item in stages] == list(expected_stages)
        first, last = stages
        assert last['active'] == 0 and last['subscribers'] == [0, 0]
        if expected_stages == (1, 2):
            assert first['active'] == 0 and first['subscribers'] == [0, 0]
            assert last['out'] > first['out'] and last['in'] > first['in']
        else:
            assert first['subscribers'] == [1, 0]
    return stages, dropped


def verify_bundle(directory, *, after=False):
    manifest = json.loads((directory / 'G12LH-bundle.json').read_text(encoding='utf-8'))
    assert set(manifest) == {'kind', 'files'} and manifest['kind'] == 'ERP_READY_POOL3_BUNDLE_V1'
    assert type(manifest['files']) is dict and set(manifest['files']) == ASSETS
    for name, digest in manifest['files'].items():
        assert type(digest) is str and re.fullmatch(r'[0-9a-f]{64}', digest)
        path = directory / name
        assert path.is_file() and not path.is_symlink() and sha(path) == digest
    allowed = ASSETS | {'G12LH-bundle.json'}
    if after:
        allowed.add('G12KZ-test-output')
    assert {path.name for path in directory.iterdir()} <= allowed


def verify_driver(driver_root, directory, workflow_sha, expected_manifest_sha, profile):
    assert re.fullmatch(r'[0-9a-f]{40}', workflow_sha)
    assert re.fullmatch(r'[0-9a-f]{64}', expected_manifest_sha)
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=driver_root, text=True).strip()
    assert git('rev-parse', 'HEAD') == workflow_sha
    subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--ignore-submodules=untracked'],
                   cwd=driver_root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    source = driver_root / profile['driverBundlePath']
    assert source.resolve().is_relative_to(driver_root.resolve())
    assert sha(directory / 'G12LH-bundle.json') == expected_manifest_sha
    assert sha(source / 'G12LH-bundle.json') == expected_manifest_sha
    for name in sorted(ASSETS | {'G12LH-bundle.json'}):
        path = source / name
        assert path.is_file() and not path.is_symlink()
        git('ls-files', '--error-unmatch', '--', path.relative_to(driver_root).as_posix())
        assert sha(path) == sha(directory / name)
    return {'driverSha': workflow_sha, 'driverBundleSHA256': expected_manifest_sha}


def configure_kernel(root, directory, profile):
    kernel_path = root / 'scripts/check_reference_catalog_ui.py'
    assert sha(kernel_path) == profile['sourceSHA256']['scripts/check_reference_catalog_ui.py']
    spec = importlib.util.spec_from_file_location('private_pool3_kernel', directory / 'G12LJ-kernel.py')
    kernel = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(kernel)
    finally:
        sys.dont_write_bytecode = previous
    kernel.ROOT = root
    kernel.PORTS = (profile['backendPort'], profile['frontendPort'])
    kernel.EXPECTED_SOURCES = dict(profile['sourceSHA256'])
    kernel.EXPECTED_MODULES = dict(profile['modulePins'])
    kernel.EXPECTED_CASES = {('pool', 'G12KZ-pool.spec.cjs', title) for title in profile['cases']}
    assert len(kernel.EXPECTED_CASES) == 3
    kernel.SELECTED = ['--config', str(directory / 'G12KZ-playwright.config.cjs')]
    source = directory / 'G12KZ-pool.spec.cjs'
    kernel.DIAGNOSTIC_SOURCES = {str(source): (1, len(source.read_text(encoding='utf-8').splitlines()))}
    original_cases, original_results, original_capture = kernel.cases, kernel.results, kernel.capture

    def cases(report, *, collection=False):
        found = original_cases(report, collection=collection)
        if collection:
            assert all(not case.get('results') for _, case in found)
        return found

    def results(report, returncode):
        summary = original_results(report, returncode)
        by_id = {case['id']: case for case in summary['cases']}
        expected = {title: (index * 2 + 1, index * 2 + 2) for index, title in enumerate(profile['cases'])}
        for stable, case in cases(report):
            attempts = case.get('results', [])
            if attempts:
                stages, dropped = pool_attachments(attempts[0], expected[stable[2]])
                row = by_id[kernel.case_id(stable)]
                row['poolStages'] = stages
                row['droppedAttachmentCount'] = dropped
        return summary

    def capture(command, temp, name, timeout):
        assert name in ('catalogue-collection', 'catalogue-execution')
        assert timeout == (90 if name == 'catalogue-collection' else 600)
        assert command[:3] == ['node', 'node_modules/@playwright/test/cli.js', 'test']
        assert command.count('--project=chromium') == 1
        assert command.count('--config') == 1
        assert command[command.index('--config') + 1] == str(directory / 'G12KZ-playwright.config.cjs')
        command = ['--project=pool' if item == '--project=chromium' else item for item in command]
        return original_capture(command, temp, name, timeout)

    kernel.cases, kernel.results, kernel.capture = cases, results, capture
    return kernel


def main():
    # This entry point is not invoked by preparation/protocol checks.
    assert sys.platform.startswith('linux') and sys.version_info[:2] == (3, 12)
    assert os.environ.get('CI') == os.environ.get('GITHUB_ACTIONS') == 'true'
    directory = Path(__file__).resolve().parent
    temp = Path(os.environ['RUNNER_TEMP']).resolve()
    root = Path(os.environ['ERP_POOL_SOURCE_ROOT']).resolve()
    assert directory.is_relative_to(temp) and root == Path.cwd().resolve()
    assert root.is_relative_to(Path(os.environ['GITHUB_WORKSPACE']).resolve())
    profile_path = directory / 'G12KZ-profile.json'
    assert os.environ.get('ERP_POOL_PROFILE', str(profile_path)) == str(profile_path)
    verify_bundle(directory)
    profile = json.loads(profile_path.read_text(encoding='utf-8'))
    assert profile['kind'] == 'ERP_READY_PRIVATE_POOL3_V1'
    assert root.name == profile['sourceRootName']
    assert profile['head'] == '6e8f316862b968dd0efcd05b4e77f2e4415294e4'
    driver_root = Path(os.environ['ERP_POOL_DRIVER_ROOT']).resolve()
    assert driver_root.is_relative_to(Path(os.environ['GITHUB_WORKSPACE']).resolve())
    assert not root.is_relative_to(driver_root) and not driver_root.is_relative_to(root)
    driver = verify_driver(driver_root, directory, os.environ['GITHUB_SHA'],
                           os.environ['ERP_POOL_EXPECTED_BUNDLE_SHA256'], profile)
    node_version = subprocess.check_output(['node', '--version'], text=True).strip()
    assert re.fullmatch(r'v20\.\d+\.\d+', node_version)
    os.environ['ERP_POOL_PROFILE'] = str(profile_path)
    os.environ['E2E_BACKEND_PORT'] = str(profile['backendPort'])
    os.environ['E2E_FRONTEND_PORT'] = str(profile['frontendPort'])
    old_summary = temp / 'erp-ready-catalogue-summary.json'
    final_summary = temp / 'erp-ready-pool-summary.json'
    assert not old_summary.exists() and not final_summary.exists()
    kernel = configure_kernel(root, directory, profile)
    result = kernel.main(application_sha=profile['head'])
    summary = json.loads(old_summary.read_text())
    # Kernel applies the source/port/owned SQLite cleanup gates on success and failure.
    verify_bundle(directory, after=True)
    assert verify_driver(driver_root, directory, os.environ['GITHUB_SHA'],
                         os.environ['ERP_POOL_EXPECTED_BUNDLE_SHA256'], profile) == driver
    summary.update(kind='pool3-real-HTTP-and-Next-lifecycle', planned=3, uiPlanned=0,
                   nodeVersion=node_version, profileSHA256=sha(profile_path),
                   applicationSha=profile['head'], kernelSHA256=sha(directory / 'G12LJ-kernel.py'), **driver)
    if summary.get('passed'):
        assert result == 0 and summary['countsKnown'] is True
        assert (summary['passedCount'], summary['failedCount'], summary['notRunCount']) == (3, 0, 0)
        assert all(summary.get(name) is True for name in (
            'sourceVerifiedAfter', 'postflightPortsClean', 'postflightDatabaseClean'))
        assert len(summary['cases']) == 3
    final_summary.write_text(json.dumps(summary, sort_keys=True) + '\n')
    return result


if __name__ == '__main__':
    sys.exit(main())
