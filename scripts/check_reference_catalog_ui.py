import base64
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

EXPECTED_SOURCES = {'frontend/e2e/auth.setup.ts': 'ce6deaa84a5ec0c290ec144340ccac8cbb9df1f94db2bdf3784db70834f0e80e', 'frontend/src/app/erp/spravochniki/sku/page.tsx': '33a4a11747e92fd4e973391ccdebc07b97e380c3a5cefca72ea8cf80ac5f8f09', 'frontend/src/app/erp/spravochniki/sku/[code]/page.tsx': '1bc0449277ee18d1cfe020defecad3cc545f6b6d728be9eb1af441c7d9e2d39a', 'frontend/src/app/crm/catalog/page.tsx': 'efa0806f852d333a3e22e55c529c66f1d790167b5800ff82c644b18dcb1da337', 'frontend/src/components/erp/spravochniki/sprav-sku-catalog.tsx': 'c25206cfd83cf78decb52c02641eb846780dc821ad43eb5a4debe577de806286', 'frontend/src/components/erp/spravochniki/sprav-sku-card.tsx': 'e2dea850141801b4d9b9a946c6486648fd7c7864fe72913d805bd91bae066a6d', 'frontend/src/lib/reference-data.ts': 'fc1634b949881d9d5b4e4a32b2e08a7719060624824a07c93ac34d364a71fe79', 'frontend/src/lib/auth-headers-server.ts': 'ff3709a380dbee1a014b712ce387f86d63a08e98ae765caa969dfce6447d68f2', 'frontend/src/lib/role-server.ts': '03e9a68b83feed9643bb77877d75c4282d8e54e96803b68b89a17fadb67f7f38', 'frontend/src/app/api/[...path]/route.ts': 'e847536bc79d9201a19501a26f237607f6b5bf4c82f33be5cb8f80effadc8839', 'frontend/src/app/api/auth/login/route.ts': '1289e9128a7b7d3fe903a7552bf054bfc35a80b3b74354ed93d2715517045802', 'frontend/package.json': '738dd786cbd85052d05f365451504fa8345a306c8769906a00b25016a93b0eda', 'frontend/package-lock.json': '06346becd5f38c81e385a8633e7f49760a94af56c841be2f74052a2cb398e0cd', 'core/runtime/app.py': '8a8f2a821f050d7f0c36ea592814bbcde253fd26ef66cb5fd2fabca9ccd8bd38', 'core/domain/models.py': '463b3d7dfad062d1ada1f5810c0d8a8fad1b3068c050fceee262b08681eec62b', 'core/services/reference_query.py': '92e458584101e085691cca12c3ff56a93a0ed05f76379c35ba591412b4d84209', 'core/runtime/system_routes.py': 'b50827e60f6babcbed7a2f8c10eb08ae4b144c95e1c54dd3d54bd394495a5c9f', 'config/settings.py': '5712caeda80cc397bfd995141f29cc5c248835718c0dc0075796fc0c43b167a4', 'requirements.txt': '119d8759052167b8bdd56aa5b6b01f2704c73816bb2e5e62b7a60a84d96ee4cc', 'requirements-dev.txt': '8f929f0992643b9814e6a4f820bf6d13658ecee6e744b8fbef906fd20bb694b0', 'frontend/e2e/reference-catalog.spec.ts': '5a296b2ecf5e230a479a196d4584ed68fa5ae9cf0c9b59bc3d7d89197bb2cdc6', 'frontend/playwright.config.ts': 'f255cf17a67f3f874ef4bcf6ed499a20bb80ae8623c39b2947a132575a45b319', 'frontend/e2e/backend.py': 'a7b1ecbdd876e19542783516cfedfd0f8071d9c310ff8e7a4057a6417b53fc45', 'frontend/src/components/erp/spravochniki/sprav-sku-catalog.test.tsx': '0c438c5d1370ff9658c53c1b4fd2a5dab913c999b846ae80a84ff7e010b303b9', 'frontend/src/app/erp/spravochniki/sku/page.test.tsx': '5931a50232b64021a350e22ceaab02c909372de815e4cbdff9dd1bc4dbbfb829'}
EXPECTED_MODULES = {'finance': '59832b2f14a2ee02d8db266a67f8206616bdcd94', 'hr': 'f8a6e0142f1920b07ec56818f42d156a602ff9c3', 'leads': '9a304f771ba74369ded199168e0e1da3ad6348d2', 'logistics': '6923d2e021980ef2546f382364d38dc34a0fef29', 'marketing': 'd4ed67fdc9b41e7abc370112e1a3fa8a3fe1e282', 'procurement': 'f29ea84bd13342ae572e8c4499031d2f053d3d47', 'production': 'be7d7e198bf09cc41c642d22125db401da5adc48', 'sales': 'c023f3f019ccd4f69da3eab100fff86c5c448691', 'service': '3d33800c44865cd7a7373b29192c5d59d3c4bec8', 'wms': '412cacfb2f2f6ebee291d1c3816901dfe59c1fa7'}
EXPECTED_CASES = {('setup', 'auth.setup.ts', 'dev-логин (Директор)'), ('chromium', 'reference-catalog.spec.ts', 'CRM каталог: данные, поиск и карточка'), ('chromium', 'reference-catalog.spec.ts', 'ERP каталог на узком экране: данные и действия'), ('chromium', 'reference-catalog.spec.ts', 'ERP каталог: данные, поиск и карточка')}
DIAGNOSTIC_SOURCES = {'frontend/e2e/auth.setup.ts': (1, 26), 'frontend/e2e/reference-catalog.spec.ts': (2, 85)}
ROOT = Path.cwd()
PORTS = (18471, 18472)
SELECTED = ['e2e/reference-catalog.spec.ts']


def case_id(stable):
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def cases(report, *, collection=False):
    output = []

    def walk(suite):
        for spec in suite.get('specs', []):
            for test in spec.get('tests', []):
                stable = (test['projectId'], Path(spec['file']).name, spec['title'])
                assert stable in EXPECTED_CASES
                output.append((stable, test))
        for child in suite.get('suites', []):
            walk(child)

    for suite in report.get('suites', []):
        walk(suite)
    assert len({stable for stable, _ in output}) == len(output)
    if collection:
        assert not report.get('errors') and {stable for stable, _ in output} == EXPECTED_CASES
    else:
        assert output or report.get('errors')
    return output


def diagnostic(error, status):
    if not isinstance(error, dict):
        error = {}
    category = {'timedOut': 2, 'interrupted': 3}.get(status, 1)
    location = error.get('location', {})
    frame = None
    if isinstance(location, dict):
        for filename, (source_id, limit) in DIAGNOSTIC_SOURCES.items():
            if location.get('file') in (filename, str(ROOT / filename), filename.removeprefix('frontend/')):
                line, column = location.get('line'), location.get('column')
                if type(line) is int and type(column) is int and 1 <= line <= limit and 1 <= column <= 4096:
                    frame = {'sourceId': source_id, 'line': line, 'column': column}
    return {'categoryId': category, 'location': frame}


def request_diagnostic(attempt):
    matches = [item for item in attempt.get('attachments', [])
               if item.get('name') == 'catalogue-http-numeric']
    if not matches:
        return None
    assert len(matches) == 1
    attachment = matches[0]
    assert set(attachment) == {'name', 'contentType', 'body'}
    assert attachment['contentType'] == 'application/json'
    body = attachment['body']
    assert isinstance(body, str) and len(body) <= 8192
    raw = base64.b64decode(body, validate=True)
    assert len(raw) <= 4096
    value = json.loads(raw)
    assert isinstance(value, dict) and set(value) == {'total', 'dropped', 'entries'}
    assert all(type(value[key]) is int and 0 <= value[key] <= 1_000_000
               for key in ('total', 'dropped'))
    entries = value['entries']
    assert isinstance(entries, list) and len(entries) <= 16
    for entry in entries:
        assert isinstance(entry, dict) and set(entry) == {'pathId', 'status'}
        assert type(entry['pathId']) is int and 0 <= entry['pathId'] <= 9
        assert type(entry['status']) is int and 400 <= entry['status'] <= 599
    assert value['total'] == len(entries) + value['dropped']
    return {'total': value['total'], 'dropped': value['dropped'],
            'entries': [{'pathId': entry['pathId'], 'status': entry['status']} for entry in entries]}


def results(report, returncode):
    assert type(returncode) is int and returncode in (0, 1)
    executed = cases(report)
    exported = []
    for stable, test in executed:
        assert test.get('expectedStatus') == 'passed'
        attempts = test.get('results', [])
        assert len(attempts) <= 1
        if not attempts:
            status = 'not_run'
        else:
            assert attempts[0].get('retry', 0) == 0
            status = attempts[0]['status']
            assert status in ('passed', 'failed', 'timedOut', 'interrupted', 'skipped')
            if status == 'skipped':
                status = 'not_run'
        value = {'id': case_id(stable), 'status': status}
        requests = request_diagnostic(attempts[0]) if attempts else None
        if status == 'passed' and stable[1] == 'reference-catalog.spec.ts':
            assert requests is not None and requests['total'] == 0
        if requests is not None:
            value['requests'] = requests
        if status in ('failed', 'timedOut', 'interrupted'):
            value['diagnostic'] = diagnostic(attempts[0].get('error'), status)
        exported.append(value)
    present = {stable for stable, _ in executed}
    exported.extend({'id': case_id(stable), 'status': 'not_run'} for stable in EXPECTED_CASES - present)
    global_errors = report.get('errors', [])
    assert isinstance(global_errors, list) and all(isinstance(error, dict) for error in global_errors)
    duration = report['stats']['duration']
    assert type(duration) in (int, float) and 0 <= duration <= 900_000
    passed = sum(case['status'] == 'passed' for case in exported)
    failed = sum(case['status'] in ('failed', 'timedOut', 'interrupted') for case in exported)
    not_run = sum(case['status'] == 'not_run' for case in exported)
    success = returncode == 0 and passed == len(EXPECTED_CASES) and not global_errors
    if returncode == 0:
        assert success
    else:
        assert failed or global_errors
    return dict(countsKnown=True, cases=sorted(exported, key=lambda case: case['id']),
                passedCount=passed, failedCount=failed, notRunCount=not_run,
                globalErrorCount=len(global_errors),
                globalDiagnostics=[diagnostic(error, 'startup') for error in global_errors[:3]],
                durationMs=int(duration), passed=success)


def verify_sources(root):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
    assert git('rev-parse', 'HEAD') == os.environ['GITHUB_SHA']
    subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--ignore-submodules=untracked'],
                   cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for filename, expected in EXPECTED_SOURCES.items():
        assert hashlib.sha256((root / filename).read_bytes()).hexdigest() == expected
    for name, expected in EXPECTED_MODULES.items():
        assert git('-C', 'modules/' + name, 'rev-parse', 'HEAD') == expected


def ports_clean():
    for port in PORTS:
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                return False
    return True


def cleanup_owned_database(allowed):
    database = ROOT / 'e2e.db'
    if not database.exists():
        return True
    assert allowed and not database.is_symlink() and ports_clean()
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
        assert connection.execute('SELECT code FROM sku ORDER BY code').fetchall() == [('QA-ORDER',), ('QA-STOCK',)]
    database.unlink()
    return not any((ROOT / name).exists() for name in ('e2e.db', 'e2e.db-wal', 'e2e.db-shm'))


def capture(command, temp, name, timeout):
    with (temp / (name + '.json')).open('wb') as out, (temp / (name + '.stderr')).open('wb') as err:
        return subprocess.run(command, cwd=ROOT / 'frontend', stdout=out, stderr=err, timeout=timeout).returncode


def main():
    temp = Path(os.environ['RUNNER_TEMP'])
    summary = dict(schemaVersion=1, kind='catalogue-rendered-ui3-plus-setup', stage='preflight', passed=False,
                   planned=4, uiPlanned=3, countsKnown=False, passedCount=None, failedCount=None, notRunCount=None,
                   cases=[], sourceVerifiedAfter=False, postflightPortsClean=False, postflightDatabaseClean=False,
                   cleanupDeferredToHostedJobTeardown=True)
    allowed_cleanup = False
    code = 1
    try:
        verify_sources(ROOT)
        assert not (ROOT / 'e2e.db').exists() and ports_clean()
        for directory in (ROOT, ROOT / 'frontend'):
            assert not any((directory / name).exists() for name in (
                '.env', '.env.local', '.env.development', '.env.development.local',
                '.env.production', '.env.production.local', '.env.test', '.env.test.local'))
        assert os.environ['E2E_BACKEND_PORT'] == str(PORTS[0])
        assert os.environ['E2E_FRONTEND_PORT'] == str(PORTS[1])
        assert not any(os.environ.get(name) for name in (
            'E2E_ISOLATED_BASE_URL', 'E2E_BACKEND_CMD', 'E2E_CHROMIUM_EXECUTABLE', 'E2E_SQLITE_PATH'))
        summary.update(commit=os.environ['GITHUB_SHA'], sourceSha256=EXPECTED_SOURCES, moduleSha=EXPECTED_MODULES)
        command = ['node', 'node_modules/@playwright/test/cli.js', 'test', *SELECTED,
                   '--project=chromium', '--workers=1', '--retries=0', '--max-failures=1', '--reporter=json']
        summary['stage'] = 'collection'
        assert capture([*command, '--list'], temp, 'catalogue-collection', 90) == 0
        listed = cases(json.loads((temp / 'catalogue-collection.json').read_text()), collection=True)
        summary['collectedIds'] = sorted(case_id(stable) for stable, _ in listed)
        summary['stage'] = 'execution'
        allowed_cleanup = True  # The known-absent local path is created only by the frozen synthetic backend.
        returncode = capture(command, temp, 'catalogue-execution', 600)
        summary.update(results(json.loads((temp / 'catalogue-execution.json').read_text()), returncode))
        summary['stage'] = 'completed'
        code = 0 if summary['passed'] else 1
    except Exception:
        summary['passed'] = False  # Exception text can contain cookies or page contents; never export it.
    finally:
        try:
            verify_sources(ROOT)
            summary['sourceVerifiedAfter'] = True
        except Exception:
            summary['passed'] = False
        try:
            summary['postflightPortsClean'] = ports_clean()
            summary['postflightDatabaseClean'] = cleanup_owned_database(allowed_cleanup)
            if not summary['postflightPortsClean'] or not summary['postflightDatabaseClean']:
                summary['passed'] = False
        except Exception:
            summary['passed'] = False
        if not summary['passed']:
            code = 1
        (temp / 'erp-ready-catalogue-summary.json').write_text(json.dumps(summary, sort_keys=True) + '\n')
        print('Catalogue stage:', summary['stage'], 'passed:', summary['passedCount'],
              'failed:', summary['failedCount'], 'not run:', summary['notRunCount'])
    return code


if __name__ == '__main__':
    sys.exit(main())
