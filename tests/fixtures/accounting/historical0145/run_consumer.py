# ruff: noqa: E402, I001
# Integrity gates precede imports; preserve the historical business import order.
"""Pinned 0145 business consumer for synthetic migration fixtures; no producer."""
import asyncio
import hashlib
import importlib
from importlib.machinery import PathFinder
import json
from pathlib import Path
import re
import sys

base = Path(__file__).resolve().parent
manifest = json.loads((base / 'manifest.json').read_text(encoding='utf-8'))
assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == manifest['runnerSHA']
root = (base / 'consumer').resolve()
phase, case = sys.argv[1:]
assert phase in {'smoke', 'consume', 'replay-zero'}
assert case in {'monetary-specific', 'monetary-weighted_average', 'zero-existing-issue'}
assert phase != 'replay-zero' or case == 'zero-existing-issue'
state = 'consumer145'
expected = set()
for item in manifest['files']:
    path = (root / item['path']).resolve()
    assert path.is_relative_to(root) and path.stat().st_size == item['bytes']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
    expected.add(path)
assert len(expected) == 38
project = {'core', 'modules', 'tests', 'config'}
assert not any(name.split('.')[0] in project for name in sys.modules)
sys.dont_write_bytecode = True

class FrozenOnly:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] not in project:
            return None
        spec = PathFinder.find_spec(fullname, [str(root)] if path is None else path)
        if spec is None:
            raise ImportError('Missing frozen project dependency: ' + fullname)
        if spec.origin is not None:
            assert Path(spec.origin).resolve() in expected
        else:
            locations = list(spec.submodule_search_locations or [])
            assert locations and all(Path(p).resolve().is_relative_to(root) for p in locations)
        return spec

def audit(event, _args):
    if event == 'subprocess.Popen':
        raise PermissionError('Historical phase must not create subprocesses')
    if event in {'sqlite3.connect', 'os.system'}:
        raise RuntimeError('Unexpected historical phase operation')

sys.meta_path.insert(0, FrozenOnly())
sys.addaudithook(audit)
if phase == 'smoke':
    def no_network(event, _args):
        if event in {'socket.connect', 'socket.bind', 'socket.getaddrinfo'}:
            raise PermissionError('Import smoke must not use the network')
    sys.addaudithook(no_network)
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

if phase != 'smoke':
    raw = sys.stdin.read(16385)
    assert len(raw) <= 16384
    payload = json.loads(raw)
    url = make_url(payload['url'])
    assert url.drivername == 'postgresql+psycopg' and url.host == '127.0.0.1' and not url.query
    assert re.fullmatch(r'acc_test_[a-f0-9]{32}', url.database or '')
    assert 1024 <= url.port <= 65535
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def run():
    engine = create_async_engine(url, connect_args={'connect_timeout': 5,
        'options': '-c statement_timeout=15000 -c lock_timeout=12000'})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as conn:
            assert await conn.scalar(text('SELECT current_database()')) == url.database
            assert 160000 <= int(await conn.scalar(text('SHOW server_version_num'))) < 170000
            marker = await conn.scalar(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"))
            assert marker == 'crm-acc-fixture:' + url.database
        from modules.accounting import models, sales, service
        from modules.accounting.production_output_cost_workflow import (
            ProductionOutputCostConfirmInput, ProductionOutputCostPreviewInput,
            confirm_output_cost_correction, preview_output_cost_correction,
        )
        org = payload['producer']['organizationId']
        if case.startswith('monetary-'):
            async with factory() as session:
                receipts = (await session.scalars(select(models.InventorySaleReceipt).where(
                    models.InventorySaleReceipt.organization_id == org).order_by(models.InventorySaleReceipt.entry_id))).all()
                assert len(receipts) == 2
                for saved in receipts:
                    document = sales.SaleDocument.model_validate(saved.command)
                    entry = await session.get(models.Entry, saved.entry_id)
                    replay = await sales.confirm(session, org, document, saved.cost['basis_digest'], entry.digest, 'tester')
                    assert replay.id == saved.entry_id
                revisions = (await session.scalars(select(models.ProductionOutputCostRevision).where(
                    models.ProductionOutputCostRevision.organization_id == org).order_by(models.ProductionOutputCostRevision.sequence))).all()
                assert len(revisions) == 3
                for saved in revisions:
                    replay = await confirm_output_cost_correction(session, org, saved.month,
                        ProductionOutputCostConfirmInput.model_validate(saved.command), saved.actor)
                    assert replay.id == saved.id
                await session.commit()
            return {'salesReplayed': 2, 'correctionsReplayed': 3}
        if phase == 'replay-zero':
            async with factory() as session:
                saved = await session.get(models.ProductionOutputCostRevision, payload['consumer']['revisionId'])
                replay = await confirm_output_cost_correction(session, org, saved.month,
                    ProductionOutputCostConfirmInput.model_validate(saved.command), saved.actor)
                assert replay.id == saved.id
                await session.commit()
            return {'revisionId': replay.id, 'replayed': True}
        from uuid import uuid4
        from modules.accounting.schemas import LineInput, PostingInput
        async with factory() as session:
            await service.post(session, org, PostingInput(source='legacy-zero-late-wip', source_version=1,
                operation='manual', document_date='2026-10-31', operation_date='2026-10-31',
                posting_date='2026-10-31', policy_id=payload['producer']['policyId'], rule_version='synthetic',
                explanation='Legacy zero issue late cost', lines=[
                    LineInput(account='20', side='debit', amount='100', dimensions={'department':'SHOP','order':'ORDER-42'}),
                    LineInput(account='60', side='credit', amount='100')]), 'tester')
            request = ProductionOutputCostPreviewInput(original_entry_id=payload['producer']['outputId'],
                posting_date='2026-10-31', request_evidence='Legacy zero receipt survives 0145')
            preview = await preview_output_cost_correction(session, org, '2026-10', request)
            assert preview['trace']['disposals'][0]['kind'] == 'zero'
            assert sorted(row['amount_byn'] for row in preview['destinations']) == ['25.00', '75.00']
            revision = await confirm_output_cost_correction(session, org, '2026-10',
                ProductionOutputCostConfirmInput(**request.model_dump(), request_key=uuid4(),
                                                 basis_digest=preview['basis_digest']), 'tester')
            await session.commit()
        return {'revisionId': revision.id, 'destinations': ['25.00', '75.00'], 'disposalKind': 'zero'}
    finally:
        await engine.dispose()


if phase == 'smoke':
    from modules.accounting import models, sales, service  # noqa: F401
    from modules.accounting import production_output_cost_workflow  # noqa: F401
    for item in manifest['files']:
        module_name = item['path'].removesuffix('.py').replace('/', '.')
        module_name = module_name.removesuffix('.__init__')
        importlib.import_module(module_name)
    for missing in ('core.domain.models', 'tests.accounting.test_postgres', 'config.modules'):
        try:
            importlib.import_module(missing)
        except ImportError:
            pass
        else:
            raise AssertionError('Current-project fallback admitted')
    result = {'importOnly': True, 'databaseUsed': False}
else:
    result = asyncio.run(run())
origins = {}
for name, module in list(sys.modules.items()):
    if name.split('.')[0] not in project:
        continue
    origin = getattr(module, '__file__', None)
    if origin is not None:
        path = Path(origin).resolve()
        assert path in expected and path.is_relative_to(root)
        origins[name] = path.relative_to(root).as_posix()
    else:
        locations = list(getattr(module, '__path__', []))
        assert locations and all(Path(p).resolve().is_relative_to(root) for p in locations)
if phase == 'smoke':
    assert set(origins.values()) == set(item['path'] for item in manifest['files'])
print(json.dumps({'passed': True, 'phase': phase, 'case': case, 'state': state,
                  'projectModules': len(origins), 'result': result}))
