import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('compatible_schema_image', HERE/'compatible_schema_image.py')
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)
path = 'migrations/versions/0195_employee_login_accounts.py'


def fixtures():
    before = {'Id': 'old', 'Image': 'old-image', 'State': {'Running': True, 'StartedAt': 'one'}, 'config': 'same'}
    staged = {'Id': 'new', 'Image': 'new-image', 'State': {'Running': False, 'StartedAt': ''}, 'config': 'same'}
    old = {'heads': ['0194'], 'files': {'entrypoint': 'entry', 'oldmigration': 'old'}}
    new = {'heads': ['0195'], 'files': {**old['files'], path: 'approved'}}
    proof = {'status': 'REAL_IDENTITY_REHEARSAL_PASS', 'migrationRoundTrip': True,
             'unsafeDowngradeBlocked': True, 'backup': {'restoreVerified': True},
             'sourceSHAs': {path: 'approved'}}
    runner = SimpleNamespace(inspect=lambda image: {'Config': {'env': 'same'}},
        image_schema=lambda image: old if image == 'old-image' else new,
        projection=lambda row: row['config'])
    update = SimpleNamespace(verify_staged_projection=lambda r, a, b, **kw: (
        None if r.projection(a) == r.projection(b) else (_ for _ in ()).throw(RuntimeError('CONFIG_CHANGED'))))
    return before, staged, old, new, proof, runner, update


def test_only_exact_additive_migration_is_accepted():
    before, staged, old, new, proof, runner, update = fixtures()
    route.verify_stage(update, runner, before, staged, 'old-image', 'new-image', proof, 'approved')
    new['files']['entrypoint'] = 'changed'
    with pytest.raises(RuntimeError, match='UNAPPROVED_MIGRATION'):
        route.verify_stage(update, runner, before, staged, 'old-image', 'new-image', proof, 'approved')


@pytest.mark.parametrize('field', ['migrationRoundTrip', 'unsafeDowngradeBlocked'])
def test_incomplete_rehearsal_never_accepts_image(field):
    before, staged, old, new, proof, runner, update = fixtures()
    proof[field] = False
    with pytest.raises(RuntimeError, match='RESTORED_POSTGRES'):
        route.verify_stage(update, runner, before, staged, 'old-image', 'new-image', proof, 'approved')


@pytest.mark.parametrize('observed', [['0194'], ['0195', 'other']])
def test_wrong_live_schema_has_no_stop_or_start(tmp_path, observed):
    before, staged, old, new, proof, runner, update = fixtures()
    calls = []
    engine = SimpleNamespace(inspect=lambda cid: before if cid == 'old' else staged,
                             request=lambda *args: calls.append(args))
    migration = {'status': 'ALEMBIC_0195_APPLIED', 'image': 'new-image', 'backupRestoreVerified': True}
    with pytest.raises(RuntimeError, match='MIGRATION_NOT_OBSERVED'):
        route.switch(update, engine, runner, tmp_path, before, staged, migration,
                     health=lambda: True, schema=lambda cid: observed)
    assert calls == [] and not list(tmp_path.iterdir())


def test_uncertain_stop_is_not_retried_and_candidate_never_starts(tmp_path):
    before, staged, old, new, proof, runner, update = fixtures()
    calls = []

    def request(method, path):
        calls.append(path)
        raise TimeoutError('response lost')

    def exclusive(path, value):
        with path.open('x') as f:
            f.write('intent')

    update.exclusive = exclusive
    engine = SimpleNamespace(inspect=lambda cid: copy.deepcopy(before if cid == 'old' else staged), request=request)
    migration = {'status': 'ALEMBIC_0195_APPLIED', 'image': 'new-image', 'backupRestoreVerified': True}
    with pytest.raises(TimeoutError):
        route.switch(update, engine, runner, tmp_path, before, staged, migration,
                     health=lambda: True, schema=lambda cid: ['0195'])
    with pytest.raises(RuntimeError, match='ALREADY_STARTED_READ_STATUS'):
        route.switch(update, engine, runner, tmp_path, before, staged, migration,
                     health=lambda: True, schema=lambda cid: ['0195'])
    assert calls == ['/containers/old/stop?t=10']


def test_switch_retains_old_and_checks_new_head(tmp_path):
    before, staged, old, new, proof, runner, update = fixtures()
    states = {'old': copy.deepcopy(before), 'new': copy.deepcopy(staged)}
    calls = []

    def request(method, path):
        calls.append(path)
        states['old' if '/old/' in path else 'new']['State']['Running'] = path.endswith('/start')

    def exclusive(path, value):
        with path.open('x') as f:
            f.write('confirmed')

    update.exclusive = exclusive
    engine = SimpleNamespace(inspect=lambda cid: copy.deepcopy(states[cid]), request=request)
    migration = {'status': 'ALEMBIC_0195_APPLIED', 'image': 'new-image', 'backupRestoreVerified': True}
    active = route.switch(update, engine, runner, tmp_path, before, staged, migration,
                          health=lambda: True, schema=lambda cid: ['0195'])
    assert active['Id'] == 'new' and active['State']['Running']
    assert states['old']['State']['Running'] is False
    assert calls == ['/containers/old/stop?t=10', '/containers/new/start']
    assert {p.name for p in tmp_path.iterdir()} == {
        'stop-intent.json', 'stop-confirmed.json', 'start-intent.json', 'start-confirmed.json',
    }


# Same-head release contract: fake Engine only; no Docker, database or network.
SAME_HEAD_IDS = [
    'C01_exact0204_stage', 'C02_same_image_refused', 'C03_wrong_base_image',
    'C04_wrong_candidate_image', 'C05_old_config_seal', 'C06_new_config_seal',
    'C07_nonlabel_drift_resealed', 'C08_unrelated_label_resealed',
    'C09_wrong_source_binding', 'C10_wrong_checkpoint_binding',
    'C11_image_head_changed', 'C12_entrypoint_or_migration_changed',
    'C13_runtime_projection_drift', 'C14_previously_started_candidate',
    'C15_live_start_identity_drift', 'C16_live_schema_wrong_no_effect',
    'C17_exact_switch_retains_old', 'C18_uncertain_stop_no_retry',
    'C19_uncertain_start_no_retry', 'C20_preexisting_intent_no_effect',
    'C21_post_projection_drift', 'C22_post_schema_changed',
    'C23_unhealthy_deadline_no_return', 'C24_old_restarts_after_start',
    'C25_schema_seal_wrong',
]


def same_head_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def same_head_fixture(monkeypatch):
    projection = same_head_module('same_head_projection', 'prepare_mixed.py')
    portable_projection = projection.projection
    # Match the installed runner's Config detachment, retaining Host/Mount aliases.
    projection.projection = lambda info: portable_projection({
        **info, 'Config': copy.deepcopy(info['Config'])})
    update = same_head_module('same_head_update', 'fresh_backend_image.py')
    base, new = 'sha256:' + '1' * 64, 'sha256:' + '2' * 64
    old_id, new_id = 'a' * 64, 'b' * 64
    config = dict(Entrypoint=['docker/app-entrypoint.sh'], Cmd=None,
                  Env=['FIXTURE=value'], User='10001:10001', WorkingDir='/app',
                  Labels={'crm-rel-001-owner': 'fixture-owner',
                          'crm-rel-001-package': 'a' * 40,
                          'crm-rel-001-source': 'c' * 64,
                          'by.enersys.crm.intake.revision': 'retained-intake',
                          'by.enersys.crm.nbrb.revision': 'retained-nbrb'})
    new_config = copy.deepcopy(config)
    new_config['Labels'].update({'crm-rel-001-package': 'b' * 40,
                                 'crm-rel-001-source': 'd' * 64})
    before = dict(Id=old_id, Name='/fixture-old', Image=base, RestartCount=0,
        Config=dict(copy.deepcopy(config), Image=base, Hostname='fixture-old'),
        HostConfig=dict(AutoRemove=False, OomKillDisable=None, Privileged=False),
        Mounts=[dict(Destination='/app/data', Source='/fixture/data', RW=True)],
        NetworkSettings=dict(Networks={'fixture-network': {}}),
        State=dict(Running=True, Status='running', Pid=101,
                   StartedAt='2026-10-31T01:00:00Z', ExitCode=0, OOMKilled=False,
                   Paused=False, Restarting=False))
    staged = copy.deepcopy(before)
    staged.update(Id=new_id, Name='/fixture-new', Image=new)
    staged['Config']['Image'] = new
    staged['State'].update(Running=False, Status='created', Pid=0,
                           StartedAt='0001-01-01T00:00:00Z')
    image_schema = dict(heads=['0204'], files={
        'alembic.ini': '1' * 64, 'docker/app-entrypoint.sh': '2' * 64,
        'migrations/versions/0204_fixture.py': '3' * 64})
    ctx = SimpleNamespace(base=base, new=new, old_id=old_id, new_id=new_id,
        before=before, staged=staged,
        states={old_id: copy.deepcopy(before), new_id: copy.deepcopy(staged)},
        images={base: dict(Id=base, Config=config),
                new: dict(Id=new, Config=new_config)},
        schemas={base: copy.deepcopy(image_schema), new: copy.deepcopy(image_schema)},
        live_heads={old_id: ['0204'], new_id: ['0204']}, effects=[],
        health_calls=[], schema_calls=[], health_hook=None, schema_hook=None,
        stop_timeout=False, start_timeout=False, clock=SimpleNamespace(now=0.0))
    ctx.seal = dict(oldImage=base, newImage=new,
        oldConfigSHA=projection.digest(config), newConfigSHA=projection.digest(new_config),
        oldCheckpoint='a' * 40, newCheckpoint='b' * 40,
        oldSourceSHA256='c' * 64, newSourceSHA256='d' * 64, schemaHeads=['0204'])
    ctx.runner = SimpleNamespace(digest=projection.digest, projection=projection.projection,
        inspect=lambda image: copy.deepcopy(ctx.images[image]),
        image_schema=lambda image: copy.deepcopy(ctx.schemas[image]))

    def request(method, path):
        ctx.effects.append((method, path))
        if path == '/containers/' + old_id + '/stop?t=10':
            ctx.states[old_id]['State'].update(Running=False, Status='exited', Pid=0,
                                               ExitCode=143)
            if ctx.stop_timeout:
                raise TimeoutError('synthetic lost stop reply')
        elif path == '/containers/' + new_id + '/start':
            ctx.states[new_id]['State'].update(Running=True, Status='running', Pid=202,
                                               StartedAt='2026-10-31T02:00:00Z')
            if ctx.start_timeout:
                raise TimeoutError('synthetic lost start reply')
        else:
            raise AssertionError('Unexpected Engine mutation')

    def health(cid):
        ctx.health_calls.append(cid)
        if ctx.health_hook is not None:
            return ctx.health_hook(cid)
        return True

    def schema(cid):
        ctx.schema_calls.append(cid)
        if ctx.schema_hook is not None:
            ctx.schema_hook(cid)
        return copy.deepcopy(ctx.live_heads[cid])

    def sleep(seconds):
        ctx.clock.now += seconds

    ctx.engine = SimpleNamespace(inspect=lambda cid: copy.deepcopy(ctx.states[cid]),
                                 request=request)
    ctx.health, ctx.schema, ctx.update = health, schema, update
    monkeypatch.setattr(route, 'time', SimpleNamespace(
        monotonic=lambda: ctx.clock.now, sleep=sleep))
    return ctx


@pytest.mark.parametrize('case', SAME_HEAD_IDS, ids=SAME_HEAD_IDS)
def test_same_head_contract(case, tmp_path, monkeypatch):
    ctx = same_head_fixture(monkeypatch)
    if case.startswith('C02'):
        ctx.seal['newImage'] = ctx.seal['oldImage']
    elif case.startswith('C03'):
        ctx.before['Image'] = ctx.new
    elif case.startswith('C04'):
        ctx.staged['Image'] = ctx.base
    elif case.startswith('C05'):
        ctx.seal['oldConfigSHA'] = '0' * 64
    elif case.startswith('C06'):
        ctx.seal['newConfigSHA'] = '0' * 64
    elif case.startswith('C07'):
        ctx.images[ctx.new]['Config']['Env'] = ['UNAPPROVED=value']
        ctx.seal['newConfigSHA'] = ctx.runner.digest(ctx.images[ctx.new]['Config'])
    elif case.startswith('C08'):
        ctx.images[ctx.new]['Config']['Labels']['by.enersys.crm.nbrb.revision'] = 'changed'
        ctx.seal['newConfigSHA'] = ctx.runner.digest(ctx.images[ctx.new]['Config'])
    elif case.startswith('C09'):
        ctx.images[ctx.new]['Config']['Labels']['crm-rel-001-source'] = 'e' * 64
        ctx.seal['newConfigSHA'] = ctx.runner.digest(ctx.images[ctx.new]['Config'])
    elif case.startswith('C10'):
        ctx.images[ctx.new]['Config']['Labels']['crm-rel-001-package'] = 'e' * 40
        ctx.seal['newConfigSHA'] = ctx.runner.digest(ctx.images[ctx.new]['Config'])
    elif case.startswith('C11'):
        ctx.schemas[ctx.new]['heads'] = ['0205']
    elif case.startswith('C12'):
        ctx.schemas[ctx.new]['files']['docker/app-entrypoint.sh'] = 'e' * 64
    elif case.startswith('C13'):
        ctx.staged['Config']['Env'] = ['UNAPPROVED=value']
    elif case.startswith('C14'):
        ctx.staged['State'].update(Status='exited', StartedAt='2026-10-31T00:00:00Z')
    elif case.startswith('C15'):
        ctx.states[ctx.old_id]['State']['StartedAt'] = '2026-10-31T00:30:00Z'
    elif case.startswith('C16'):
        ctx.live_heads[ctx.old_id] = ['0200']
    elif case.startswith('C18'):
        ctx.stop_timeout = True
    elif case.startswith('C19'):
        ctx.start_timeout = True
    elif case.startswith('C20'):
        (tmp_path / 'start-intent.json').write_text('{}', encoding='utf8')
    elif case.startswith('C21'):
        def drift(cid):
            ctx.states[cid]['Config']['Env'] = ['DRIFT_DURING_HEALTH=value']
            return True
        ctx.health_hook = drift
    elif case.startswith('C22'):
        ctx.live_heads[ctx.new_id] = ['0205']
    elif case.startswith('C23'):
        def late_health(cid):
            ctx.clock.now = 61.0
            return True
        ctx.health_hook = late_health
    elif case.startswith('C24'):
        def restart_old(cid):
            if cid == ctx.new_id:
                ctx.states[ctx.old_id]['State'].update(
                    Running=True, Status='running', Pid=303,
                    StartedAt='2026-10-31T02:30:00Z')
        ctx.schema_hook = restart_old
    elif case.startswith('C25'):
        ctx.seal['schemaHeads'] = ['0200']

    def switch():
        return route.switch_same_schema(ctx.update, ctx.engine, ctx.runner, tmp_path,
            ctx.before, ctx.staged, ctx.seal, health=ctx.health, schema=ctx.schema)

    if case.startswith('C01'):
        assert route.verify_same_schema_stage(ctx.update, ctx.runner, ctx.before,
                                              ctx.staged, ctx.seal) is None
        assert ctx.effects == [] and not list(tmp_path.iterdir())
    elif int(case[1:3]) <= 14 or case.startswith('C25'):
        with pytest.raises(RuntimeError):
            route.verify_same_schema_stage(ctx.update, ctx.runner, ctx.before,
                                           ctx.staged, ctx.seal)
        assert ctx.effects == [] and not list(tmp_path.iterdir())
    elif case.startswith('C17'):
        active = switch()
        assert active['Id'] == ctx.new_id and active['State']['Running']
        assert not ctx.states[ctx.old_id]['State']['Running']
        assert ctx.states[ctx.old_id]['State']['Pid'] == 0
        assert ctx.states[ctx.old_id]['State']['ExitCode'] == 143
        assert set(ctx.states) == {ctx.old_id, ctx.new_id}
        assert ctx.effects == [('POST', '/containers/' + ctx.old_id + '/stop?t=10'),
                               ('POST', '/containers/' + ctx.new_id + '/start')]
        assert ctx.health_calls == [ctx.new_id]
        assert ctx.schema_calls == [ctx.old_id, ctx.new_id]
        assert {p.name for p in tmp_path.iterdir()} == {
            'stop-intent.json', 'stop-confirmed.json',
            'start-intent.json', 'start-confirmed.json'}
    elif case.startswith(('C18', 'C19')):
        with pytest.raises(TimeoutError):
            switch()
        effects = list(ctx.effects)
        with pytest.raises(RuntimeError, match='ALREADY_STARTED'):
            switch()
        assert ctx.effects == effects
        assert len(effects) == (1 if case.startswith('C18') else 2)
        assert (tmp_path / 'stop-intent.json').is_file()
        assert not (tmp_path / 'start-confirmed.json').exists()
        assert ctx.health_calls == []
    elif case.startswith(('C15', 'C16', 'C20')):
        with pytest.raises(RuntimeError):
            switch()
        assert ctx.effects == [] and ctx.health_calls == []
    else:
        with pytest.raises(RuntimeError):
            switch()
        assert ctx.effects == [('POST', '/containers/' + ctx.old_id + '/stop?t=10'),
                               ('POST', '/containers/' + ctx.new_id + '/start')]
        assert ctx.health_calls == [ctx.new_id]
        assert set(ctx.states) == {ctx.old_id, ctx.new_id}



REVIEW_REGRESSION_IDS = [
    'R01_auto_remove_cannot_retain_base',
    'R02_pre_stop_callback_cannot_rebind_stage_time',
    'R03_post_callback_cannot_change_config_image',
]


@pytest.mark.parametrize('case', REVIEW_REGRESSION_IDS, ids=REVIEW_REGRESSION_IDS)
def test_same_head_review_regressions(case, tmp_path, monkeypatch):
    ctx = same_head_fixture(monkeypatch)
    if case.startswith('R01'):
        # Matching projections are insufficient when stopping deletes the base.
        for info in (ctx.before, ctx.staged, *ctx.states.values()):
            info['HostConfig']['AutoRemove'] = True
        with pytest.raises(RuntimeError):
            route.verify_same_schema_stage(ctx.update, ctx.runner, ctx.before,
                                           ctx.staged, ctx.seal)
        assert ctx.effects == []
        return
    if case.startswith('R02'):
        def rebind_stage(cid):
            if cid == ctx.old_id:
                changed = '2026-10-31T00:30:00Z'
                ctx.staged['State']['StartedAt'] = changed
                ctx.states[ctx.new_id]['State']['StartedAt'] = changed
        ctx.schema_hook = rebind_stage
    else:
        def change_image(cid):
            ctx.states[cid]['Config']['Image'] = ctx.base
            return True
        ctx.health_hook = change_image
    with pytest.raises(RuntimeError):
        route.switch_same_schema(ctx.update, ctx.engine, ctx.runner, tmp_path,
            ctx.before, ctx.staged, ctx.seal, health=ctx.health, schema=ctx.schema)
    if case.startswith('R02'):
        assert ctx.effects == []
        assert not list(tmp_path.iterdir())
    else:
        assert ctx.effects == [('POST', '/containers/' + ctx.old_id + '/stop?t=10'),
                               ('POST', '/containers/' + ctx.new_id + '/start')]
        assert set(ctx.states) == {ctx.old_id, ctx.new_id}



# Return contracts use the forward path to create actual fake runtime history.
RETURN_IDS = [
    'T01_running_return', 'T02_exited_return',
    'T03_created_no_start_attempt_return', 'T04_wrong_image_seal',
    'T05_pre_schema_changed', 'T06_new_identity_drift', 'T07_old_identity_drift',
    'T08_old_start_drift', 'T09_observed_candidate_start_drift',
    'T10_candidate_projection_drift', 'T11_old_projection_drift',
    'T12_candidate_config_image_drift', 'T13_old_config_image_drift',
    'T14_actual_autoremove_drift', 'T15_matching_non_no_restart_policy_refused',
    'T16_candidate_restarting_refused', 'T17_candidate_paused_refused',
    'T18_old_not_stopped_refused', 'T19_created_with_unknown_start_intent_refused',
    'T20_exited_epoch_start_refused', 'T21_missing_forward_stop_intent',
    'T22_foreign_forward_start_intent', 'T23_existing_return_stop_intent',
    'T24_existing_return_stop_confirmed', 'T25_existing_return_start_intent',
    'T26_existing_return_start_confirmed', 'T27_uncertain_candidate_stop_no_retry',
    'T28_uncertain_old_start_no_retry', 'T29_late_health_true_refused',
    'T30_post_schema_changed', 'T31_post_old_projection_drift',
    'T32_candidate_restarts_during_post_schema',
    'T33_pre_schema_cannot_rebind_old_start', 'T34_exited_oom_candidate_return',
    'T35_dangling_return_marker_refused',
    'T36_post_callback_cannot_rebind_expected_projection',
    'T37_late_schema_head_refused', 'T38_deadline_includes_base_start',
    'T39_exited_without_start_intent_refused',
    'T40_start_intent_without_stop_confirmed_refused',
]


def return_fixture(tmp_path, monkeypatch, case):
    ctx = same_head_fixture(monkeypatch)
    for info in (ctx.before, ctx.staged, *ctx.states.values()):
        info['HostConfig']['RestartPolicy'] = {'Name': 'no', 'MaximumRetryCount': 0}
    ctx.oom_attested = case.startswith('T03')
    if ctx.oom_attested:
        ctx.staged['HostConfig']['OomKillDisable'] = False
        ctx.states[ctx.new_id]['HostConfig']['OomKillDisable'] = False
        ctx.stop_timeout = True
    original_request = ctx.engine.request
    if case.startswith('T19'):
        def unknown_start(method, path):
            if path == '/containers/' + ctx.new_id + '/start':
                raise TimeoutError('synthetic start outcome unresolved before effect')
            return original_request(method, path)
        ctx.engine.request = unknown_start
    if case.startswith(('T03', 'T19')):
        with pytest.raises(TimeoutError):
            route.switch_same_schema(ctx.update, ctx.engine, ctx.runner, tmp_path,
                ctx.before, ctx.staged, ctx.seal, health=ctx.health,
                schema=ctx.schema, oom_lifecycle_verified=ctx.oom_attested)
    else:
        route.switch_same_schema(ctx.update, ctx.engine, ctx.runner, tmp_path,
            ctx.before, ctx.staged, ctx.seal, health=ctx.health, schema=ctx.schema)
    if case.startswith(('T02', 'T34', 'T39')):
        ctx.states[ctx.new_id]['State'].update(Running=False, Status='exited', Pid=0,
            ExitCode=137 if case.startswith('T34') else 1,
            OOMKilled=case.startswith('T34'), FinishedAt='2026-10-31T03:00:00Z')
    ctx.observed = copy.deepcopy(ctx.states[ctx.new_id])
    ctx.forward_markers = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    ctx.effects.clear()
    ctx.health_calls.clear()
    ctx.schema_calls.clear()
    ctx.reverse_stop_timeout = False
    ctx.reverse_start_timeout = False
    ctx.reverse_start_late = False

    def reverse_request(method, path):
        assert method == 'POST'
        ctx.effects.append((method, path))
        if path == '/containers/' + ctx.new_id + '/stop?t=10':
            ctx.states[ctx.new_id]['State'].update(Running=False, Status='exited',
                Pid=0, ExitCode=143, FinishedAt='2026-10-31T03:00:00Z')
            if ctx.reverse_stop_timeout:
                raise TimeoutError('synthetic lost candidate stop reply')
        elif path == '/containers/' + ctx.old_id + '/start':
            ctx.states[ctx.old_id]['State'].update(Running=True, Status='running',
                Pid=303, StartedAt='2026-10-31T03:30:00Z', ExitCode=0,
                FinishedAt='0001-01-01T00:00:00Z')
            ctx.states[ctx.old_id]['RestartCount'] = 0
            if ctx.reverse_start_late:
                ctx.clock.now = 61.0
            if ctx.reverse_start_timeout:
                raise TimeoutError('synthetic lost retained base start reply')
        else:
            raise AssertionError('Unexpected return mutation')

    ctx.engine.request = reverse_request
    return ctx


@pytest.mark.parametrize('case', RETURN_IDS, ids=RETURN_IDS)
def test_same_head_return(case, tmp_path, monkeypatch):
    import json

    ctx = return_fixture(tmp_path, monkeypatch, case)
    number = int(case[1:3])
    if number == 4:
        ctx.seal['newConfigSHA'] = '0' * 64
    elif number == 5:
        ctx.live_heads[ctx.old_id] = ['0205']
    elif number == 6:
        ctx.states[ctx.new_id]['Image'] = ctx.base
    elif number == 7:
        ctx.states[ctx.old_id]['Image'] = ctx.new
    elif number == 8:
        ctx.states[ctx.old_id]['State']['StartedAt'] = '2026-10-31T00:30:00Z'
    elif number == 9:
        ctx.states[ctx.new_id]['State']['StartedAt'] = '2026-10-31T02:30:00Z'
    elif number in (10, 11):
        ctx.states[ctx.new_id if number == 10 else ctx.old_id]['Config']['Env'] = ['DRIFT=value']
    elif number in (12, 13):
        ctx.states[ctx.new_id if number == 12 else ctx.old_id]['Config']['Image'] = 'sha256:' + '9' * 64
    elif number == 14:
        ctx.states[ctx.new_id]['HostConfig']['AutoRemove'] = True
    elif number == 15:
        for info in (ctx.before, ctx.staged, ctx.observed, *ctx.states.values()):
            info['HostConfig']['RestartPolicy'] = {'Name': 'unless-stopped', 'MaximumRetryCount': 0}
    elif number == 16:
        ctx.states[ctx.new_id]['State']['Restarting'] = True
    elif number == 17:
        ctx.states[ctx.new_id]['State']['Paused'] = True
    elif number == 18:
        ctx.states[ctx.old_id]['State'].update(Running=True, Status='running', Pid=101)
    elif number == 20:
        ctx.states[ctx.new_id]['State'].update(Running=False, Status='exited', Pid=0,
            StartedAt='0001-01-01T00:00:00Z')
        ctx.observed = copy.deepcopy(ctx.states[ctx.new_id])
    elif number == 21:
        (tmp_path / 'stop-intent.json').unlink()
    elif number == 22:
        (tmp_path / 'start-intent.json').write_text(json.dumps(
            {'id': 'e' * 64, 'status': 'ATTEMPTED_UNKNOWN'}), encoding='utf-8')
    elif number in (23, 24, 25, 26):
        names = {23: 'return-stop-intent.json', 24: 'return-stop-confirmed.json',
                 25: 'return-start-intent.json', 26: 'return-start-confirmed.json'}
        (tmp_path / names[number]).write_text('{}', encoding='utf-8')
    elif number == 27:
        ctx.reverse_stop_timeout = True
    elif number == 28:
        ctx.reverse_start_timeout = True
    elif number == 29:
        def late_health(cid):
            ctx.clock.now = 61.0
            return True
        ctx.health_hook = late_health
    elif number in (30, 32, 37):
        def post_schema(cid):
            if len(ctx.schema_calls) == 2:
                if number == 30:
                    ctx.live_heads[cid] = ['0205']
                elif number == 32:
                    ctx.states[ctx.new_id]['State'].update(Running=True, Status='running',
                        Pid=404, StartedAt='2026-10-31T04:00:00Z')
                else:
                    ctx.clock.now = 61.0
        ctx.schema_hook = post_schema
    elif number in (31, 36):
        def post_projection(cid):
            ctx.states[cid]['Config']['Env'] = ['DRIFT_DURING_HEALTH=value']
            if number == 36:
                ctx.before['Config']['Env'] = ['DRIFT_DURING_HEALTH=value']
            return True
        ctx.health_hook = post_projection
    elif number == 33:
        def pre_schema(cid):
            if len(ctx.schema_calls) == 1:
                stamp = '2026-10-31T01:30:00Z'
                ctx.before['State']['StartedAt'] = stamp
                ctx.states[ctx.old_id]['State']['StartedAt'] = stamp
        ctx.schema_hook = pre_schema
    elif number == 35:
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(Path, 'is_symlink', lambda path:
            path.name == 'return-start-intent.json' or original_is_symlink(path))
    elif number == 38:
        ctx.reverse_start_late = True
    elif number == 39:
        (tmp_path / 'start-intent.json').unlink()
        (tmp_path / 'start-confirmed.json').unlink()
    elif number == 40:
        (tmp_path / 'stop-confirmed.json').unlink()

    def return_to_base():
        return route.return_same_schema(ctx.update, ctx.engine, ctx.runner, tmp_path,
            ctx.before, ctx.staged, ctx.observed, ctx.seal, health=ctx.health,
            schema=ctx.schema, oom_lifecycle_verified=ctx.oom_attested)

    expected = [('POST', '/containers/' + ctx.new_id + '/stop?t=10'),
                ('POST', '/containers/' + ctx.old_id + '/start')]
    if number in (1, 2, 3, 34):
        active = return_to_base()
        assert active['Id'] == ctx.old_id and active['State']['Running']
        assert ctx.runner.projection(active) == ctx.runner.projection(ctx.before)
        assert not ctx.states[ctx.new_id]['State']['Running']
        assert ctx.states[ctx.new_id]['State']['Pid'] == 0
        assert set(ctx.states) == {ctx.old_id, ctx.new_id}
        assert ctx.effects == (expected if number == 1 else expected[1:])
        assert ctx.health_calls == [ctx.old_id]
        assert ctx.schema_calls == [ctx.old_id, ctx.old_id]
        for name, raw in ctx.forward_markers.items():
            assert (tmp_path / name).read_bytes() == raw
        assert {p.name for p in tmp_path.iterdir() if p.name.startswith('return-')} == {
            'return-stop-intent.json', 'return-stop-confirmed.json',
            'return-start-intent.json', 'return-start-confirmed.json'}
        proof = json.loads((tmp_path / 'return-stop-confirmed.json').read_text())
        assert proof['id'] == ctx.new_id and proof['stopped'] is True
        assert proof['method'] == ('POST' if number == 1 else 'OBSERVED_NO_RESTART')
        if number == 3:
            assert ctx.states[ctx.new_id]['State']['Status'] == 'created'
            assert ctx.states[ctx.new_id]['HostConfig']['OomKillDisable'] is False
            assert active['HostConfig']['OomKillDisable'] is None
        if number == 34:
            assert ctx.states[ctx.new_id]['State']['OOMKilled'] is True
    elif number in (27, 28):
        with pytest.raises(TimeoutError):
            return_to_base()
        effects = list(ctx.effects)
        with pytest.raises(RuntimeError, match='ALREADY_RETURN'):
            return_to_base()
        assert ctx.effects == effects == (expected[:1] if number == 27 else expected)
        assert not (tmp_path / 'return-start-confirmed.json').exists()
        assert ctx.health_calls == []
    elif number in (29, 30, 31, 32, 36, 37, 38):
        with pytest.raises(RuntimeError):
            return_to_base()
        assert ctx.effects == expected
        assert ctx.health_calls == ([] if number == 38 else [ctx.old_id])
        assert set(ctx.states) == {ctx.old_id, ctx.new_id}
    else:
        with pytest.raises(RuntimeError):
            return_to_base()
        assert ctx.effects == [] and ctx.health_calls == []
        assert not any(p.name.startswith('return-') for p in tmp_path.iterdir()
                       if number not in (23, 24, 25, 26))


CALLBACK_CASES = [
    'P01_health_old', 'P02_health_candidate', 'P03_health_unhealthy',
    'P04_health_timeout', 'P05_health_nonzero', 'P06_health_output_limit',
    'P07_health_protocol', 'P08_schema_stopped_app', 'P09_schema_candidate',
    'P10_schema_changed', 'P11_schema_empty', 'P12_schema_two_heads',
    'P13_schema_nonzero', 'P14_schema_timeout', 'P15_schema_output_limit',
    'P16_schema_protocol', 'P17_binding_frozen', 'P18_unapproved_app',
    'P19_pg_is_not_app', 'P20_invalid_cid', 'P21_distinct_ids',
    'P22_database_scope', 'P23_app_user', 'P24_binding_fields',
    'P25_binding_type', 'P26_stdout_type', 'P27_error_privacy',
    'P28_health_late', 'P29_schema_late', 'P30_inner_health',
    'P31_schema_transport', 'P32_no_constructor_effect',
]


@pytest.mark.parametrize('case', CALLBACK_CASES, ids=CALLBACK_CASES)
def test_bounded_same_schema_callback(monkeypatch, case):
    import subprocess
    import traceback

    factory = route.same_schema_callbacks
    old, new, pg = 'a' * 64, 'b' * 64, 'c' * 64
    binding = dict(appIDs=[old, new], pgID=pg, database='aios', appUser='10001:10001')
    calls = []
    ctx = SimpleNamespace(stdout=b'HEALTHY\n', returncode=0, error=None,
                          clock=0.0, advance=0.0)

    def run(args, **kwargs):
        calls.append((copy.deepcopy(args), copy.deepcopy(kwargs)))
        ctx.clock += ctx.advance
        if ctx.error is not None:
            raise ctx.error
        return SimpleNamespace(stdout=ctx.stdout, returncode=ctx.returncode,
                               stderr=b'EXTERNAL_PRIVATE_ERROR')

    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(route.time, 'monotonic', lambda: ctx.clock)
    number = int(case[1:3])
    if number in (20, 21, 22, 23, 24, 25):
        variants = []
        if number == 20:
            variants = [{**binding, 'pgID': 'postgres'},
                        {**binding, 'appIDs': [old, 'B' * 64]},
                        {**binding, 'appIDs': [old, 'short']}]
        elif number == 21:
            variants = [{**binding, 'appIDs': [old, old]},
                        {**binding, 'pgID': old}]
        elif number == 22:
            variants = [{**binding, 'database': v} for v in
                        ('postgres', 'template0', 'template1', 'bad;SELECT 1',
                         'host=remote dbname=x', '', '-option', 'a' * 64)]
        elif number == 23:
            variants = [{**binding, 'appUser': v} for v in
                        ('root', '10001', '-u 0', '', None, '1:2:3')]
        elif number == 24:
            variants = [{**binding, 'extra': True},
                        {k: v for k, v in binding.items() if k != 'pgID'}]
        else:
            variants = [None, [], 'not-a-binding', True]
        for variant in variants:
            with pytest.raises(RuntimeError):
                factory(variant)
        assert calls == []
        return

    health, schema = factory(binding)
    assert calls == []
    if number == 17:
        binding['appIDs'][:] = ['d' * 64, 'e' * 64]
        binding.update(pgID='f' * 64, database='elsewhere', appUser='123:456')
    if number in (18, 19):
        for callback in (health, schema):
            with pytest.raises(RuntimeError):
                callback('d' * 64 if number == 18 else pg)
        assert calls == []
        return
    if number in (4, 14):
        ctx.error = subprocess.TimeoutExpired('fixed-command', 3, output=b'PRIVATE')
    if number in (5, 13):
        ctx.returncode = 1
    if number in (6, 15):
        ctx.stdout = b'x' * 1025
    if number == 7:
        ctx.stdout = b'UNKNOWN\n'
    if number == 26:
        ctx.stdout = 'HEALTHY\n'
    if number in (28, 29):
        ctx.advance = 3.01 if number == 28 else 15.01
    if number == 27:
        secret = 'PRIVATE_SENTINEL_374'
        for error in (OSError(secret), subprocess.TimeoutExpired(secret, 3, output=secret)):
            ctx.error = error
            for callback in (health, schema):
                with pytest.raises(RuntimeError) as caught:
                    callback(old)
                assert secret not in str(caught.value)
                assert secret not in ''.join(traceback.format_exception(caught.value))
        return
    if number == 16:
        for raw in (b'0204\n0204\n', b'0205\n0204\n', b'0203\n0204\n0205\n',
                    b'0204\n\n', b'0204;DROP\n', b'\xff', b'0204'):
            ctx.stdout = raw
            with pytest.raises(RuntimeError):
                schema(old)
        return
    if number in (4, 5, 6, 7, 13, 14, 15, 26, 28, 29):
        if number in (13, 29):
            ctx.stdout = b'0204\n'
        callback = schema if number in (13, 14, 15, 29) else health
        expected_error = {
            4: 'PROBE_UNAVAILABLE_OR_TIMEOUT', 5: 'PROBE_COMMAND_FAILED_REDACTED',
            6: 'PROBE_OUTPUT_LIMIT', 7: 'HEALTH_PROBE_PROTOCOL',
            13: 'PROBE_COMMAND_FAILED_REDACTED', 14: 'PROBE_UNAVAILABLE_OR_TIMEOUT',
            15: 'PROBE_OUTPUT_LIMIT', 26: 'PROBE_OUTPUT_LIMIT',
            28: 'PROBE_LATE_RESULT', 29: 'PROBE_LATE_RESULT',
        }[number]
        with pytest.raises(RuntimeError, match='^' + expected_error + '$'):
            callback(old)
        assert len(calls) == 1
        return

    if number in (1, 2, 3, 17, 30, 32):
        if number == 3:
            ctx.stdout = b'UNHEALTHY\n'
        assert health(new if number == 2 else old) is (number != 3)
        args, options = calls[-1]
        assert args[:4] == ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'exec']
        assert args[4:9] == ['--user', '10001:10001', old if number != 2 else new, 'python', '-I']
        assert args[9:12] == ['-S', '-B', '-c']
        assert options['timeout'] == 3
    if number in (8, 9, 10, 11, 12, 17, 31, 32):
        ctx.stdout = {10: b'0205\n', 11: b'', 12: b'0203\n0204\n'}.get(number, b'0204\n')
        expected = {10: ['0205'], 11: [], 12: ['0203', '0204']}.get(number, ['0204'])
        assert schema(new if number == 9 else old) == expected
        args, options = calls[-1]
        assert args[:5] == ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'exec', pg]
        assert options['timeout'] == 15
        assert args[args.index('-d') + 1] == 'aios'
        if number in (8, 9):
            assert len(calls) == 1 and old not in args and new not in args
    if number in (17, 31, 32):
        for args, options in calls:
            assert options['env'] == {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'HOME': '/nonexistent'}
            assert options['stdin'] == subprocess.DEVNULL
            assert options['stderr'] == subprocess.DEVNULL
            assert options['stdout'] == subprocess.PIPE
            assert options['shell'] is False and options['check'] is False
        if number == 31:
            args = calls[-1][0]
            assert args[5:7] == ['/usr/bin/env', '-i']
            assert 'PGCONNECT_TIMEOUT=2' in args
            assert 'PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=10000 -c lock_timeout=2000' in args
            index = args.index('/usr/bin/timeout')
            assert args[index:index + 4] == ['/usr/bin/timeout', '--signal=KILL', '12s', 'psql']
            assert all(v in args for v in ('-X', '-w', '-Atq', '/var/run/postgresql', 'aios', '--set=ON_ERROR_STOP=1'))
            sql = [args[i + 1] for i, value in enumerate(args) if value == '-c']
            assert sql == ['BEGIN READ ONLY', 'SET LOCAL statement_timeout=10000',
                           'SET LOCAL lock_timeout=2000',
                           'SELECT version_num FROM public.alembic_version ORDER BY version_num LIMIT 3',
                           'ROLLBACK']
    if number == 30:
        program = calls[-1][0][-1]
        import builtins
        for status, failure in ((200, None), (503, None), (None, OSError()),
                                (None, ValueError())):
            events, printed = [], []

            class HTTPError(Exception):
                pass

            class Connection:
                def __init__(self, host, port, *, timeout):
                    assert (host, port, timeout) == ('127.0.0.1', 8000, 1.5)
                    events.append('connect')

                def request(self, method, path):
                    assert (method, path) == ('GET', '/health')
                    events.append('request')

                def getresponse(self):
                    if failure is not None:
                        raise HTTPError() if isinstance(failure, ValueError) else failure
                    return SimpleNamespace(status=status)

                def close(self):
                    events.append('close')

            signals = SimpleNamespace(SIGALRM='alarm', SIG_DFL='default', ITIMER_REAL='real',
                                      signal=lambda *v: events.append(('signal', v)),
                                      setitimer=lambda *v: events.append(('timer', v)))
            client = SimpleNamespace(HTTPConnection=Connection, HTTPException=HTTPError)

            def import_probe(name, *args, **kwargs):
                events.append(('import', name))
                assert name in ('signal', 'http.client')
                return signals if name == 'signal' else SimpleNamespace(client=client)

            namespace = dict(vars(builtins), __import__=import_probe,
                             print=lambda value: printed.append(value))
            exec(compile(program, '<fixed-health-probe>', 'exec'), {'__builtins__': namespace})
            assert printed == ['HEALTHY' if status == 200 else 'UNHEALTHY']
            assert events.index(('signal', ('alarm', 'default'))) < events.index(('timer', ('real', 2)))
            assert events.index(('timer', ('real', 2))) < events.index(('import', 'http.client'))
            assert events[-1] == 'close'


IMAGE_CACHE_CASES = [
    'K01_canonical_old_schema', 'K02_existing_stage_verifier', 'K03_no_probe',
    'K04_unknown_image', 'K05_missing_candidate', 'K06_input_frozen',
    'K07_independent_results', 'K08_fresh_inspect', 'K09_base_methods',
    'K10_manifest_hash', 'K11_receipt_hash', 'K12_duplicate_json_keys',
    'K13_manifest_encoding_shape_limit', 'K14_receipt_encoding_shape_limit',
    'K15_pin_formats', 'K16_artifact_fields_types', 'K17_native_status',
    'K18_native_image', 'K19_native_source', 'K20_native_checkpoint',
    'K21_native_head', 'K22_native_flags_types', 'K23_manifest_binding',
    'K24_manifest_source_digest', 'K25_canonical_paths', 'K26_file_hashes_count',
    'K27_required_schema_files', 'K28_other_source_delta',
    'K29_schema_delta_visible', 'K30_artifact_scope',
]


def image_cache_fixture():
    import hashlib
    import json

    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def make(image, files, checkpoint='a' * 40):
        source = digest(files)
        manifest = dict(files=files, head='0204', package_checkpoint=checkpoint)
        receipt = dict(status='IMMUTABLE_BACKEND_IMAGE_VERIFIED', image=image,
                       source_sha256=source, package_checkpoint=checkpoint, head='0204',
                       native_pdf_bytes=3657, production_changes=0, release_ready=False,
                       probe_state_root='/fixture/accepted-native-image-verification')
        result = dict(sourceSHA256=source, checkpoint=checkpoint)
        for key, value in (('manifest', manifest), ('receipt', receipt)):
            raw = json.dumps(value, sort_keys=True).encode()
            result[key + 'Bytes'] = raw
            result[key + 'SHA256'] = hashlib.sha256(raw).hexdigest()
        return result

    def replace(artifact, key, updates=None, raw=None):
        result = copy.deepcopy(artifact)
        if raw is None:
            data = json.loads(result[key + 'Bytes'])
            data.update(updates)
            raw = json.dumps(data, sort_keys=True).encode()
        result[key + 'Bytes'] = raw
        result[key + 'SHA256'] = hashlib.sha256(raw).hexdigest()
        return result

    old, new = 'sha256:' + '1' * 64, 'sha256:' + '2' * 64
    files = {'alembic.ini': '1' * 64, 'docker/app-entrypoint.sh': '2' * 64,
             'migrations/versions/0204_fixture.py': '3' * 64,
             'migrations/__init__.py': '4' * 64, 'core/service.py': '5' * 64}
    calls = []
    images = {old: dict(Id=old, Config={'fixture': 'old'}),
              new: dict(Id=new, Config={'fixture': 'new'})}

    def inspect(image):
        calls.append(('inspect', image))
        return copy.deepcopy(images[image])

    def original_schema(image):
        raise AssertionError('Native image probe must not be repeated')

    base = SimpleNamespace(inspect=inspect, digest=digest,
                           projection=lambda info: info['fixture'], image_schema=original_schema)
    return SimpleNamespace(old=old, new=new, files=files, calls=calls, images=images,
                           make=make, replace=replace, digest=digest, base=base)


@pytest.mark.parametrize('case', IMAGE_CACHE_CASES, ids=IMAGE_CACHE_CASES)
def test_cached_native_image_schema(monkeypatch, case):

    factory = route.cached_image_schema_runner
    ctx = image_cache_fixture()
    number = int(case[1:3])
    old_artifact = ctx.make(ctx.old, ctx.files)
    new_files = {**ctx.files, 'core/service.py': '6' * 64}
    artifacts = {ctx.old: old_artifact, ctx.new: ctx.make(ctx.new, new_files, 'b' * 40)}

    def refuse(artifact, code):
        with pytest.raises(RuntimeError, match='^' + code + '$'):
            factory(ctx.base, {ctx.old: artifact})

    if number in (2, 29):
        changed_paths = [None] if number == 2 else [
            'alembic.ini', 'docker/app-entrypoint.sh', 'migrations/versions/0204_fixture.py']
        for changed_path in changed_paths:
            live = same_head_fixture(monkeypatch)
            latest = dict(new_files)
            if changed_path is not None:
                latest[changed_path] = '9' * 64
            pair = {ctx.old: old_artifact, ctx.new: ctx.make(ctx.new, latest, 'b' * 40)}
            for prefix, image in (('old', live.base), ('new', live.new)):
                live.images[image]['Config']['Labels']['crm-rel-001-source'] = pair[image]['sourceSHA256']
                live.seal[prefix + 'SourceSHA256'] = pair[image]['sourceSHA256']
                live.seal[prefix + 'ConfigSHA'] = live.runner.digest(live.images[image]['Config'])
            for snapshot in (live.before, live.staged):
                snapshot['Config']['Labels']['crm-rel-001-source'] = old_artifact['sourceSHA256']
            live.runner.image_schema = lambda image: (_ for _ in ()).throw(
                AssertionError('Do not repeat accepted native image probes'))
            cached = factory(live.runner, pair)
            if changed_path is None:
                route.verify_same_schema_stage(live.update, cached, live.before, live.staged, live.seal)
            else:
                with pytest.raises(RuntimeError, match='^SAME_SCHEMA_MIGRATION_OR_ENTRYPOINT_CHANGED$'):
                    route.verify_same_schema_stage(live.update, cached, live.before, live.staged, live.seal)
            assert live.effects == []
        return
    if number == 10:
        refuse({**old_artifact, 'manifestSHA256': 'f' * 64}, 'IMAGE_SCHEMA_CACHE_HASH')
        return
    if number == 11:
        refuse({**old_artifact, 'receiptSHA256': 'f' * 64}, 'IMAGE_SCHEMA_CACHE_HASH')
        return
    if number == 12:
        for key in ('manifest', 'receipt'):
            raw = old_artifact[key + 'Bytes']
            duplicate = raw[:-1] + b',"head":"0204"}'
            refuse(ctx.replace(old_artifact, key, raw=duplicate), 'IMAGE_SCHEMA_CACHE_DUPLICATE_KEY')
        return
    if number in (13, 14):
        key, maximum = ('manifest', 2 * 1024 * 1024) if number == 13 else ('receipt', 16384)
        for raw, error in ((b'{invalid', 'IMAGE_SCHEMA_CACHE_JSON'),
                           (b'\xff', 'IMAGE_SCHEMA_CACHE_JSON'),
                           (b'[]', 'IMAGE_SCHEMA_CACHE_MANIFEST' if number == 13 else 'IMAGE_SCHEMA_CACHE_NATIVE_PROOF'),
                           (b'x' * (maximum + 1), 'IMAGE_SCHEMA_CACHE_BYTES_LIMIT')):
            refuse(ctx.replace(old_artifact, key, raw=raw), error)
        if number == 13:
            refuse(ctx.make(ctx.old, []), 'IMAGE_SCHEMA_CACHE_FILES')
        return
    if number == 15:
        for field, value in (('manifestSHA256', 'bad'), ('receiptSHA256', 'F' * 64),
                             ('sourceSHA256', True), ('checkpoint', 'a' * 39)):
            refuse({**old_artifact, field: value}, 'IMAGE_SCHEMA_CACHE_PIN')
        with pytest.raises(RuntimeError, match='^IMAGE_SCHEMA_CACHE_IMAGE_ID$'):
            factory(ctx.base, {'latest': old_artifact})
        return
    if number == 16:
        for artifact in (None, {**old_artifact, 'extra': True},
                         {k: v for k, v in old_artifact.items() if k != 'receiptBytes'}):
            refuse(artifact, 'IMAGE_SCHEMA_CACHE_FIELDS')
        for value in (bytearray(old_artifact['manifestBytes']), '{}', None):
            refuse({**old_artifact, 'manifestBytes': value}, 'IMAGE_SCHEMA_CACHE_BYTES_LIMIT')
        return
    if number in (17, 18, 19, 20, 21):
        field, value = {17: ('status', 'CLAIMED_PASS'), 18: ('image', ctx.new),
                        19: ('source_sha256', 'f' * 64), 20: ('package_checkpoint', 'b' * 40),
                        21: ('head', '0205')}[number]
        refuse(ctx.replace(old_artifact, 'receipt', {field: value}), 'IMAGE_SCHEMA_CACHE_NATIVE_PROOF')
        return
    if number == 22:
        for field, values in (('production_changes', (False, 0.0, 1)),
                              ('release_ready', (0, True, 'false')),
                              ('native_pdf_bytes', (True, 0, -1, 1.5))):
            for value in values:
                refuse(ctx.replace(old_artifact, 'receipt', {field: value}), 'IMAGE_SCHEMA_CACHE_NATIVE_PROOF')
        return
    if number == 23:
        for field, value in (('package_checkpoint', 'b' * 40), ('head', '0205')):
            refuse(ctx.replace(old_artifact, 'manifest', {field: value}), 'IMAGE_SCHEMA_CACHE_MANIFEST_BINDING')
        return
    if number == 24:
        refuse(ctx.replace(old_artifact, 'manifest', {'files': new_files}), 'IMAGE_SCHEMA_CACHE_SOURCE_BINDING')
        return
    if number == 25:
        for bad in ('/outside.py', '../outside.py', 'core/../outside.py', 'core\\outside.py',
                    'C:/outside.py', 'core/./outside.py', './outside.py', 'core//outside.py',
                    'core/outside.py/', '.', 'core/bad\nname.py', 'core/bad\x00name.py'):
            refuse(ctx.make(ctx.old, {**ctx.files, bad: 'f' * 64}), 'IMAGE_SCHEMA_CACHE_PATH')
        return
    if number == 26:
        for value in ('bad', True, 'F' * 64, 'a' * 63):
            refuse(ctx.make(ctx.old, {**ctx.files, 'core/service.py': value}), 'IMAGE_SCHEMA_CACHE_FILE_HASH')
        refuse(ctx.make(ctx.old, {}), 'IMAGE_SCHEMA_CACHE_FILES')
        many = {**ctx.files, **{f'core/file{i}.py': 'a' * 64 for i in range(10001)}}
        refuse(ctx.make(ctx.old, many), 'IMAGE_SCHEMA_CACHE_FILES')
        return
    if number == 27:
        for name in ('alembic.ini', 'docker/app-entrypoint.sh', 'migrations/versions/0204_fixture.py'):
            refuse(ctx.make(ctx.old, {k: v for k, v in ctx.files.items() if k != name}), 'IMAGE_SCHEMA_CACHE_SCHEMA_FILES')
        return
    if number == 30:
        third = 'sha256:' + '3' * 64
        for value in (None, [], {}, {**artifacts, third: ctx.make(third, ctx.files, 'c' * 40)}):
            with pytest.raises(RuntimeError, match='^IMAGE_SCHEMA_CACHE_ARTIFACTS$'):
                factory(ctx.base, value)
        return

    cached = factory(ctx.base, {ctx.old: old_artifact} if number == 5 else artifacts)
    assert ctx.calls == []
    expected = {'heads': ['0204'], 'files': {k: v for k, v in ctx.files.items() if k != 'core/service.py'}}
    if number in (1, 3):
        assert cached.image_schema(ctx.old) == expected
        assert cached.image_schema(ctx.new) == expected
        assert ctx.calls == []
    elif number in (4, 5):
        with pytest.raises(RuntimeError, match='^IMAGE_SCHEMA_CACHE_SCOPE$'):
            cached.image_schema(ctx.new if number == 5 else 'sha256:' + 'f' * 64)
        assert ctx.calls == []
    elif number == 6:
        artifacts[ctx.old]['manifestBytes'] = b'changed'
        artifacts[ctx.old]['receiptBytes'] = b'changed'
        artifacts.clear()
        ctx.files['alembic.ini'] = '0' * 64
        assert cached.image_schema(ctx.old) == expected
    elif number == 7:
        first = cached.image_schema(ctx.old)
        first['files']['alembic.ini'] = '0' * 64
        first['heads'].append('0205')
        assert cached.image_schema(ctx.old) == expected
    elif number == 8:
        assert cached.inspect(ctx.old) == ctx.images[ctx.old]
        assert ctx.calls == [('inspect', ctx.old)]
        ctx.images[ctx.old]['Id'] = ctx.new
        with pytest.raises(RuntimeError, match='^IMAGE_SCHEMA_CACHE_INSPECT_ID$'):
            cached.inspect(ctx.old)
        with pytest.raises(RuntimeError, match='^IMAGE_SCHEMA_CACHE_SCOPE$'):
            cached.inspect('sha256:' + 'f' * 64)
        assert ctx.calls == [('inspect', ctx.old), ('inspect', ctx.old)]
    elif number == 9:
        digest = ctx.base.digest
        ctx.base.digest = lambda value: 'changed'
        assert cached.digest({'hello': 'world'}) == digest({'hello': 'world'})
        assert cached.projection({'fixture': 'projected'}) == 'projected'
    elif number == 28:
        assert old_artifact['sourceSHA256'] != artifacts[ctx.new]['sourceSHA256']
        assert cached.image_schema(ctx.old) == cached.image_schema(ctx.new)


# 381: existing-entrypoint integration, fake runtime and existing lease only.
ENTRYPOINT_CASES = ['E%02d' % n for n in range(1, 37)]


def entrypoint_fixture(tmp_path, monkeypatch):
    import contextlib
    import hashlib
    import json
    ctx = same_head_fixture(monkeypatch)
    ctx.root = tmp_path / 'release'
    ctx.root.mkdir(mode=0o700)
    ctx.pg_id = 'c' * 64
    ctx.database = 'erp_' + 'd' * 32 + '_production'
    ctx.url = 'postgresql+asyncpg://aios:fixture@pg-fixture/' + ctx.database
    ctx.url_sha = hashlib.sha256(ctx.url.encode()).hexdigest()
    ctx.changes = {ctx.old_id: [], ctx.new_id: []}
    ctx.config_calls, ctx.lease_checks, ctx.trace = [], [], []
    ctx.config_failure = None
    ctx.lease_ok = True
    for row in (ctx.before, ctx.staged):
        row['HostConfig'].update(RestartPolicy={'Name': 'no', 'MaximumRetryCount': 0})
        row['NetworkSettings']['Networks']['fixture-network'] = {
            'NetworkID': 'network-fixture', 'Aliases': ['app-fixture'], 'IPAddress': '172.20.0.3'}
        row['Config']['Env'] = ['AIOS_DATABASE_URL=' + ctx.url, 'AIOS_AI_ENABLED=false']
    ctx.pg = copy.deepcopy(ctx.before)
    ctx.pg.update(Id=ctx.pg_id, Name='/pg-fixture', Image='sha256:' + '3' * 64)
    ctx.pg['State']['Health'] = dict(Status='healthy', FailingStreak=0, Log=[])
    ctx.pg['Config']['Env'] = ['POSTGRES_DB=' + ctx.database, 'POSTGRES_USER=aios']
    ctx.pg['NetworkSettings']['Networks']['fixture-network'].update(
        Aliases=['pg-fixture'], IPAddress='172.20.0.2')
    cache = image_cache_fixture()
    files = dict(cache.files, **{
        'config/__init__.py': 'a79e374991bf7d0525594ebdde0691ee21502027a15bb3e8443835be45ef860a',
        'config/settings.py': '5712caeda80cc397bfd995141f29cc5c248835718c0dc0075796fc0c43b167a4'})
    ctx.artifacts = {ctx.base: cache.make(ctx.base, files),
                     ctx.new: cache.make(ctx.new, {**files, 'core/service.py': '6' * 64}, 'b' * 40)}
    for prefix, image in (('old', ctx.base), ('new', ctx.new)):
        ctx.images[image]['Config']['Labels']['crm-rel-001-source'] = ctx.artifacts[image]['sourceSHA256']
        ctx.seal[prefix + 'SourceSHA256'] = ctx.artifacts[image]['sourceSHA256']
        ctx.seal[prefix + 'ConfigSHA'] = ctx.runner.digest(ctx.images[image]['Config'])
    for row in (ctx.before, ctx.staged):
        row['Config']['Labels']['crm-rel-001-source'] = ctx.artifacts[ctx.base]['sourceSHA256']
    ctx.states = {r['Id']: copy.deepcopy(r) for r in (ctx.before, ctx.staged, ctx.pg)}
    ctx.profile = dict(route='SAME_SCHEMA_0204', oldContainer=ctx.old_id,
                       oldName='fixture-old', postgresContainer=ctx.pg_id,
                       database=ctx.database, owner='fixture-owner')
    ctx.profile['sameSchema'] = dict(format='ERP_READY_SAME_SCHEMA_0204_V1',
        seal=ctx.seal, before='before.json', staged='staged.json', postgres='pg.json',
        databaseURLSHA256=ctx.url_sha, compatibilityProof='compatibility.json',
        admittedModes=['preflight', 'apply', 'observe', 'recover'],
        oomLifecycleVerified=False, artifacts={})
    ctx.files = {}

    def save(name, data):
        raw = data if type(data) is bytes else json.dumps(data, sort_keys=True).encode()
        (ctx.root / name).write_bytes(raw)
        ctx.files[name] = hashlib.sha256(raw).hexdigest()

    ctx.save = save
    for name, row in (('before.json', ctx.before), ('staged.json', ctx.staged), ('pg.json', ctx.pg)):
        save(name, row)
    save('compatibility.json', dict(state='PASS_SOURCE_CONDITIONAL',
         oldSourceSHA256=ctx.seal['oldSourceSHA256'], newSourceSHA256=ctx.seal['newSourceSHA256'],
         conditions=['AI_OFF', 'UNCHANGED_SEALED_CONFIGURATION']))
    for n, (image, artifact) in enumerate(ctx.artifacts.items()):
        paths = dict(manifest='source%d.json' % n, receipt='native%d.json' % n)
        ctx.profile['sameSchema']['artifacts'][image] = paths
        for key, name in paths.items():
            save(name, artifact[key + 'Bytes'])

    def reseal():
        save('profile.json', ctx.profile)
        ctx.manifest = dict(files=dict(ctx.files))
        (ctx.root / 'manifest.json').write_text(json.dumps(ctx.manifest, sort_keys=True))

    ctx.reseal = reseal
    save('compatible_schema_image.py', (HERE/'compatible_schema_image.py').read_bytes())
    save('fresh_backend_image.py', (HERE/'fresh_backend_image.py').read_bytes())
    reseal()
    # Fixture is test data. Windows text checkouts may use CRLF; the renderer
    # itself still requires the exact original raw bytes in a real package.
    ctx.original = (HERE/'fixtures/accepted_entrypoint_7a8.py.txt').read_bytes().replace(b'\r\n', b'\n')
    assert hashlib.sha256(ctx.original).hexdigest() == '7a8b047dbe202dd8de18947d881378e41edc4abe311abc8f11055ac19bbe8567'
    original_request = ctx.engine.request

    def request(method, path):
        if method == 'GET':
            ctx.trace.append(('changes', path.split('/')[2]))
            assert path.endswith('/changes')
            return copy.deepcopy(ctx.changes[path.split('/')[2]])
        assert ctx.trace[-1] == ('lease', 123), ctx.trace[-8:]
        assert ctx.trace[-6] == ('inspect', ctx.pg_id), ctx.trace[-8:]
        assert [event[0] for event in ctx.trace[-6:]] == ['inspect', 'inspect', 'changes', 'inspect', 'changes', 'lease']
        ctx.trace.append(('POST', path))
        if path == '/containers/' + ctx.new_id + '/stop?t=10':
            ctx.effects.append((method, path))
            ctx.states[ctx.new_id]['State'].update(Running=False, Status='exited', Pid=0)
        elif path == '/containers/' + ctx.old_id + '/start':
            ctx.effects.append((method, path))
            ctx.states[ctx.old_id]['State'].update(Running=True, Status='running', Pid=303,
                                                  StartedAt='2026-10-31T03:00:00Z')
        else:
            original_request(method, path)

    ctx.engine.request = request
    def inspect(cid):
        ctx.trace.append(('inspect', cid))
        return copy.deepcopy(ctx.states[cid])
    ctx.engine.inspect = inspect
    ctx.runner.image_schema = lambda *_: (_ for _ in ()).throw(AssertionError('NO_REPEAT_NATIVE_PROBE'))

    @contextlib.contextmanager
    def lease():
        ctx.lease_checks.append('enter')
        try:
            yield 123
        finally:
            ctx.lease_checks.append('exit')

    def assert_lease(fd):
        assert fd == 123
        ctx.lease_checks.append('assert')
        ctx.trace.append(('lease', fd))
        if not ctx.lease_ok:
            raise RuntimeError('LEASE_NOT_HELD')

    ctx.leaves = SimpleNamespace(release_lease=lease)
    ctx.core = SimpleNamespace(_pg_fence_lease=assert_lease,
                              private_probe_root=lambda path: None)
    monkeypatch.setattr(route, 'same_schema_callbacks', lambda binding: (ctx.health, ctx.schema))

    def config(cid):
        ctx.config_calls.append(cid)
        if ctx.config_failure == cid:
            raise RuntimeError('CONFIGURATION_PROBE_FAILED')
        return True

    ctx.fake_config = config
    monkeypatch.setattr(route, 'same_schema_configuration_probe', lambda binding: config)
    ctx.call = lambda mode: route.run_same_schema_current(ctx.root, ctx.profile, ctx.manifest,
        mode, ctx.leaves, ctx.core, ctx.runner, ctx.update, ctx.engine)
    return ctx


@pytest.mark.parametrize('case', ENTRYPOINT_CASES, ids=ENTRYPOINT_CASES)
def test_existing_same_schema_entrypoint(case, tmp_path, monkeypatch):
    import ast
    import hashlib
    import json
    import subprocess
    # Baseline: no caller, renderer or effective-config probe existed at 380.
    renderer = route.extend_same_schema_entrypoint
    config_factory = route.same_schema_configuration_probe
    ctx = entrypoint_fixture(tmp_path, monkeypatch)
    n = int(case[1:])
    if n <= 5:
        if n == 2:
            with pytest.raises(RuntimeError, match='^ACCEPTED_ENTRYPOINT_CHANGED$'):
                renderer(ctx.original + b'\n')
        else:
            out = renderer(ctx.original).decode()
            marker = "flow=module('operation',ROOT/'operation.py');adapter_module=module('current_adapter',ROOT/'adapter.py')"
            before, after = ctx.original.decode().split(marker)
            assert out.startswith(before) and out.endswith(marker + after)
            assert out.count('run_same_schema_current') == 1
            assert "if 'route' in p:" in out and "p['route']=='SAME_SCHEMA_0204'" in out
            assert 'fresh_backend_image.py' in out and 'compatible_schema_image.py' in out
            compile(out, '<rendered-entrypoint>', 'exec')
            branch = next(x for x in ast.parse(out).body if isinstance(x, ast.If)
                          and ast.unparse(x.test) == "'route' in p")
            if n in (3, 4):
                seen = []
                def require(ok, code):
                    if not ok:
                        raise RuntimeError(code)
                def module(name, path):
                    seen.append(str(path))
                    return SimpleNamespace(run_same_schema_current=lambda *a: seen.append(a) or {},
                                           Engine=lambda: ctx.engine)
                ns = dict(p={'route': 'SAME_SCHEMA_0204' if n == 3 else 'WRONG'},
                          require=require, module=module, ROOT=ctx.root, manifest=ctx.manifest,
                          sys=SimpleNamespace(argv=['entry', 'observe', 'hash']), leaves=ctx.leaves,
                          k=ctx.core, r=ctx.runner, helper_ns={'Engine': lambda: ctx.engine},
                          json=json, print=lambda *_: None)
                if n == 3:
                    with pytest.raises(SystemExit) as exited:
                        exec(compile(ast.Module(body=[branch], type_ignores=[]), '<branch>', 'exec'), ns)
                    assert exited.value.code == 0 and len(seen) == 3
                    assert seen[-1][3] == 'observe' and seen[-1][-1] is ctx.engine
                else:
                    for bad_route in ('WRONG', None, 0, False):
                        ns['p']['route'] = bad_route
                        with pytest.raises(RuntimeError, match='^UNKNOWN_RELEASE_ROUTE$'):
                            exec(compile(ast.Module(body=[branch], type_ignores=[]), '<branch>', 'exec'), ns)
                    assert seen == []
            assert ctx.effects == [] and ctx.lease_checks == []
        return
    if n == 36:
        for mode in ('finalize', 'migrate', 'restore'):
            result = ctx.call(mode)
            assert result['safeCode'] == 'SOURCE_MODE' and ctx.effects == []
            assert not any((ctx.root/name).exists() for name in ('preflight', 'apply', 'recover'))
        return
    if n == 19:
        monkeypatch.setattr(route, 'same_schema_configuration_probe', config_factory)
        calls = []
        monkeypatch.setattr(subprocess, 'run', lambda args, **kw: (
            calls.append((args, kw)) or SimpleNamespace(returncode=0, stdout=b'BINDING_OK\n')))
        check = config_factory(dict(appIDs=[ctx.old_id, ctx.new_id], appUser='10001:10001',
                                    databaseURLSHA256=ctx.url_sha))
        assert check(ctx.old_id) is True
        args, kw = calls[0]
        assert args[:6] == ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'exec', '--user', '10001:10001']
        assert args[6:11] == [ctx.old_id, 'python', '-I', '-B', '-c']
        assert kw['timeout'] == 5 and kw['shell'] is False and kw['stderr'] == subprocess.DEVNULL
        assert "setitimer(signal.ITIMER_REAL, 4)" in args[-1]
        assert 'get_settings()' in args[-1] and 'create_app' not in args[-1]
        assert ctx.url not in args[-1]
        compile(args[-1], '<fixed-settings-probe>', 'exec')
        # Execute the actual inner program; a fake stdout alone missed a real
        # ImportError. The package deliberately exports no top-level getter.
        import sys
        import types
        source_root = HERE.parents[1]
        source_bytes = {name: (source_root/name).read_bytes().replace(b'\r\n', b'\n')
                        for name in ('config/__init__.py', 'config/settings.py')}
        class ProbePath:
            def __init__(self, name):
                self.name = name
            def __truediv__(self, name):
                return ProbePath(self.name + '/' + name)
            def is_symlink(self):
                return False
            def read_bytes(self):
                return source_bytes[self.name.removeprefix('/app/')]
        package = types.ModuleType('config')
        package.__path__ = []
        settings_module = types.ModuleType('config.settings')
        effective = SimpleNamespace(ai_enabled=False, llm_base_url='', database_url=ctx.url)
        settings_module.get_settings = lambda: effective
        fake_pathlib = types.ModuleType('pathlib')
        fake_pathlib.Path = ProbePath
        fake_signal = SimpleNamespace(SIGALRM=14, SIG_DFL=0, ITIMER_REAL=0,
                                     signal=lambda *a: None, setitimer=lambda *a: None)
        with monkeypatch.context() as inner:
            inner.setitem(sys.modules, 'config', package)
            inner.setitem(sys.modules, 'config.settings', settings_module)
            inner.setitem(sys.modules, 'pathlib', fake_pathlib)
            inner.setitem(sys.modules, 'signal', fake_signal)
            inner.setattr(sys, 'path', list(sys.path))
            exec(compile(args[-1], '<actual-inner-probe>', 'exec'), {})
            for field, bad in (('ai_enabled', True), ('llm_base_url', 'https://provider.invalid'),
                               ('database_url', ctx.url + '_other')):
                saved = getattr(effective, field)
                setattr(effective, field, bad)
                with pytest.raises(AssertionError):
                    exec(compile(args[-1], '<actual-inner-probe>', 'exec'), {})
                setattr(effective, field, saved)
        for raw in (b'WRONG\n', b'BINDING_OK\nsecret', b'x' * 1025):
            monkeypatch.setattr(subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=raw))
            with pytest.raises(RuntimeError):
                check(ctx.old_id)
        with pytest.raises(RuntimeError, match='^CONFIGURATION_PROBE_SCOPE$'):
            check(ctx.pg_id)
        def timeout(*a, **k):
            raise subprocess.TimeoutExpired('fixed', 5)
        monkeypatch.setattr(subprocess, 'run', timeout)
        with pytest.raises(RuntimeError, match='^CONFIGURATION_PROBE_UNAVAILABLE$'):
            check(ctx.old_id)
        return
    if n in (6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18):
        expected = {
            6: 'SOURCE_PACKAGE_HASH', 7: 'SOURCE_PACKAGE_PATH', 8: 'SOURCE_PROFILE_BINDING',
            9: 'SOURCE_SNAPSHOT_BINDING', 10: 'IMAGE_SCHEMA_CACHE_NATIVE_PROOF',
            11: 'SOURCE_SETTINGS_CHANGED', 12: 'LEASE_NOT_HELD',
            13: 'POSTGRES_BINDING_DRIFT', 14: 'POSTGRES_BINDING_DRIFT',
            15: 'DATABASE_NETWORK_BINDING', 16: 'DATABASE_URL_BINDING',
            17: 'DATABASE_URL_BINDING', 18: 'WRITABLE_CONFIGURATION_CHANGED'}[n]
        if n == 6:
            (ctx.root / 'before.json').write_text('{}')
        elif n == 7:
            ctx.manifest['files']['../escape'] = 'a' * 64
            (ctx.root / 'manifest.json').write_text(json.dumps(ctx.manifest))
        elif n == 8:
            ctx.profile['owner'] = 'unsealed'
        elif n == 9:
            changed = copy.deepcopy(ctx.before)
            changed['Id'] = ctx.new_id
            ctx.save('before.json', changed)
            ctx.reseal()
        elif n == 10:
            good = json.loads((ctx.root / 'compatibility.json').read_bytes())
            for bad in ({**good, 'newSourceSHA256': 'f' * 64}, {**good, 'conditions': ['AI_OFF']}):
                ctx.save('compatibility.json', bad)
                ctx.reseal()
                refusal = ctx.call('preflight')
                assert refusal['safeCode'] == 'SOURCE_COMPATIBILITY_BINDING' and ctx.effects == []
            ctx.save('compatibility.json', good)
            ctx.reseal()
            key = ctx.profile['sameSchema']['artifacts'][ctx.new]['receipt']
            proof = json.loads((ctx.root / key).read_bytes())
            proof['image'] = ctx.base
            ctx.save(key, proof)
            ctx.reseal()
        elif n == 11:
            key = ctx.profile['sameSchema']['artifacts'][ctx.new]['manifest']
            value = json.loads((ctx.root / key).read_bytes())
            value['files']['.env'] = 'f' * 64
            # This must be rejected before cache digest validation, even when separately sealed.
            ctx.save(key, value)
            ctx.reseal()
        elif n == 12:
            ctx.lease_ok = False
        elif n in (13, 14):
            if n == 13:
                ctx.states[ctx.pg_id]['State']['Health']['Status'] = 'unhealthy'
                assert ctx.call('observe')['safeCode'] == 'POSTGRES_BINDING_DRIFT'
                ctx.states[ctx.pg_id]['State']['Health']['Status'] = 'healthy'
                ctx.states[ctx.pg_id]['State']['Health']['Log'] = [{'Start': 'new', 'End': 'new', 'Output': 'healthy'}]
                assert ctx.call('observe')['status'] == 'OBSERVED_ONLY'
                ctx.states[ctx.pg_id]['State']['StartedAt'] = 'restarted'
            else:
                ctx.states[ctx.pg_id]['HostConfig']['Privileged'] = True
        elif n == 15:
            for cid in (ctx.old_id, ctx.new_id):
                ctx.states[cid]['NetworkSettings']['Networks']['fixture-network']['NetworkID'] = 'other'
        elif n == 16:
            ctx.profile['sameSchema']['databaseURLSHA256'] = 'e' * 64
            ctx.reseal()
        elif n == 17:
            for row in (ctx.before, ctx.staged, ctx.states[ctx.old_id], ctx.states[ctx.new_id]):
                row['Config']['Env'][0] = 'AIOS_DATABASE_URL=' + ctx.url.replace('aios:', 'wrong:')
            ctx.profile['sameSchema']['databaseURLSHA256'] = hashlib.sha256(ctx.url.replace('aios:', 'wrong:').encode()).hexdigest()
            ctx.save('before.json', ctx.before)
            ctx.save('staged.json', ctx.staged)
            ctx.reseal()
        else:
            for path, kind in [('/app', 1), ('/app', 2), ('/app/config', 1), ('/app/config', 2),
                               ('/app/config/settings.py', 0), ('/app/config/__init__.py', 2)]:
                ctx.changes[ctx.old_id] = [{'Path': path, 'Kind': kind}]
                assert ctx.call('observe')['safeCode'] == 'WRITABLE_CONFIGURATION_CHANGED'
            ctx.changes[ctx.old_id] = [{'Path': '/app/.env', 'Kind': 1}]
        result = ctx.call('preflight')
        assert result['status'] == 'OPERATION_HOLD_REQUIRES_OBSERVATION' and result['safeCode'] == expected
        assert ctx.effects == [] and not (ctx.root / 'preflight.json').exists()
        return
    if n == 18:  # covered in the negative group above
        raise AssertionError('unreachable')
    if n == 26:
        ctx.config_failure = ctx.old_id
        assert ctx.call('preflight')['status'] == 'OPERATION_HOLD_REQUIRES_OBSERVATION'
        ctx.config_failure = None
        result = ctx.call('observe')
        assert result['status'] == 'OBSERVED_ONLY' and result['attempt'] == 'preflight'
        assert result['operationStatus'] == 'UNKNOWN' and ctx.effects == []
        return
    if n == 20:
        # Docker API semantics: modified ancestor metadata and added bytecode.
        ctx.changes[ctx.old_id] = [dict(Path='/app', Kind=0), dict(Path='/app/config', Kind=0),
            dict(Path='/app/config/__pycache__/settings.cpython-312.pyc', Kind=1)]
    pre = ctx.call('preflight')
    assert pre['status'] == 'SAME_SCHEMA_PREFLIGHT_PASS', pre
    assert pre['releaseReady'] is False and ctx.effects == []
    assert ctx.config_calls == [ctx.old_id]
    if n in (20, 21, 26):
        if n == 21:
            assert ctx.call('preflight')['safeCode'] == 'EXISTING_ATTEMPT_OBSERVE_NO_RETRY'
        if n == 26:
            result = ctx.call('observe')
            assert result['status'] == 'OBSERVED_ONLY' and result['attempt'] == 'preflight'
        assert ctx.effects == []
        return
    if n in (31, 32):
        if n == 31:
            ctx.config_failure = ctx.old_id
        else:
            ctx.states[ctx.pg_id]['Config']['Env'].append('CHANGED=true')
        result = ctx.call('apply')
        assert result['status'] == 'OPERATION_HOLD_REQUIRES_OBSERVATION'
        assert ctx.effects == []
        return
    if n in (24, 25):
        ctx.stop_timeout = n == 24
        ctx.start_timeout = n == 25
    if n == 33:
        ctx.config_failure = ctx.new_id
    result = ctx.call('apply')
    if n in (24, 25, 33):
        assert result['status'] == 'OPERATION_HOLD_REQUIRES_OBSERVATION'
        assert (ctx.root / 'apply/stop-intent.json').is_file()
        assert not (ctx.root / 'apply/pending.json').exists()
        expected_effects = 1 if n == 24 else 2
        assert len(ctx.effects) == expected_effects
        assert ctx.call('apply')['safeCode'] == 'EXISTING_ATTEMPT_OBSERVE_NO_RETRY'
        assert len(ctx.effects) == expected_effects
        if n in (24, 25):
            observed = ctx.call('observe')
            assert observed['operationStatus'] == 'UNKNOWN'
            assert observed['markers']['stop-intent.json']['exists'] is True
            ctx.states[ctx.pg_id]['State']['StartedAt'] = 'drift'
            failed = ctx.call('observe')
            assert failed['operationStatus'] == 'UNKNOWN' and failed['markers']['stop-intent.json']['exists']
            assert len(ctx.effects) == expected_effects
        return
    assert result['status'] == 'BACKEND_SWITCHED_UI_PENDING', result
    assert result['releaseReady'] is False
    assert ctx.config_calls == [ctx.old_id, ctx.old_id, ctx.new_id]
    if n in (22, 23, 27, 35):
        if n == 27:
            count = len(ctx.effects)
            observed = ctx.call('observe')
            assert observed['status'] == 'OBSERVED_ONLY' and observed['runningIDs'] == [ctx.new_id]
            assert len(ctx.effects) == count
            marker = ctx.root/'apply/start-confirmed.json'
            original = marker.read_bytes()
            marker.write_text('{"id": "foreign", "running": true}')
            assert ctx.call('observe')['operationStatus'] == 'UNKNOWN'
            marker.write_bytes(original)
            (ctx.root/'recover').mkdir()
            assert ctx.call('observe')['operationStatus'] == 'UNKNOWN'
        if n == 35:
            assert not any('final' in p.name or 'baseline' in p.name for p in ctx.root.rglob('*'))
        assert len(ctx.effects) == 2
        return
    if n == 29:
        ctx.profile['sameSchema']['admittedModes'].remove('recover')
        ctx.reseal()
        assert ctx.call('recover')['safeCode'] == 'SOURCE_MODE_NOT_ADMITTED'
        assert len(ctx.effects) == 2
        return
    if n == 30:
        ctx.states[ctx.new_id]['State'].update(Running=False, Status='exited', Pid=0)
    if n == 34:
        ctx.config_failure = ctx.old_id
    returned = ctx.call('recover')
    if n == 34:
        assert returned['status'] == 'OPERATION_HOLD_REQUIRES_OBSERVATION'
        assert not (ctx.root / 'apply/returned.json').exists()
        return
    assert returned['status'] == 'RETURNED_UI_PENDING', returned
    assert returned['releaseReady'] is False and ctx.states[ctx.old_id]['State']['Running'] is True
    assert len(ctx.effects) == (3 if n == 30 else 4)
    if n == 28:
        count = len(ctx.effects)
        assert ctx.call('observe')['runningIDs'] == [ctx.old_id]
        assert len(ctx.effects) == count
        assert ctx.call('recover')['safeCode'] == 'ALREADY_RETURNING_READ_STATUS'
        assert len(ctx.effects) == count


# 383: explicit, sealed historical OOM proof; never native deployment authority.
OOM_PROOF_CASES = ['O%02d' % n for n in range(1, 13)]


def oom_lifecycle_fixture(tmp_path, monkeypatch):
    import json
    ctx = entrypoint_fixture(tmp_path, monkeypatch)
    # Synthetic protocol fixture, never production provenance or admission.
    ctx.oom_raw = json.dumps(dict(productionUnchanged=True, removed=True,
        status='OWNED_OOM_LIFECYCLE_PROBE', values=dict(created=False, running=None))).encode()
    ctx.profile['sameSchema'].update(oomLifecycleVerified=True, oomLifecycleProof='oom.json')
    ctx.staged['HostConfig']['OomKillDisable'] = False
    ctx.states[ctx.new_id]['HostConfig']['OomKillDisable'] = False
    ctx.save('staged.json', ctx.staged)
    ctx.save('oom.json', ctx.oom_raw)
    ctx.reseal()
    ctx.normalize_oom_at_start = True
    original_request = ctx.engine.request

    def request(method, path):
        try:
            return original_request(method, path)
        finally:
            if method == 'POST' and path == '/containers/'+ctx.new_id+'/start' and ctx.normalize_oom_at_start:
                ctx.states[ctx.new_id]['HostConfig']['OomKillDisable'] = None
    ctx.engine.request = request
    return ctx


@pytest.mark.parametrize('case', OOM_PROOF_CASES, ids=OOM_PROOF_CASES)
def test_sealed_oom_lifecycle(case, tmp_path, monkeypatch):
    import hashlib
    import json
    factory = route.verified_oom_lifecycle
    n = int(case[1:])
    ctx = oom_lifecycle_fixture(tmp_path, monkeypatch)
    sha = hashlib.sha256(ctx.oom_raw).hexdigest()
    assert sha == '62e588da9fc536b50cb1d0f64c2db1a993214373167046f97dcbadfbf124429f'

    def refuse(raw, expected, pin=None):
        with pytest.raises(RuntimeError, match='^'+expected+'$'):
            factory(raw, hashlib.sha256(raw).hexdigest() if pin is None else pin)

    if n == 1:
        assert len(ctx.oom_raw) == 132 and factory(ctx.oom_raw, sha) is True
        assert factory(json.dumps(json.loads(ctx.oom_raw), indent=2).encode(),
                       hashlib.sha256(json.dumps(json.loads(ctx.oom_raw), indent=2).encode()).hexdigest()) is True
        assert ctx.effects == [] and ctx.config_calls == []
        return
    if n == 2:
        refuse(ctx.oom_raw, 'OOM_PROOF_HASH', '0'*64)
        for pin in (None, '', 'A'*64, 1):
            with pytest.raises(RuntimeError, match='^OOM_PROOF_INPUT$'):
                factory(ctx.oom_raw, pin)
        with pytest.raises(RuntimeError, match='^OOM_PROOF_INPUT$'):
            factory(bytearray(ctx.oom_raw), sha)
        return
    if n == 3:
        for raw in (b'[]', b'null', b'{bad', b'\xff', b'x'*4097,
                    ctx.oom_raw[:-1]+b',"removed":true}'):
            refuse(raw, 'OOM_PROOF_INPUT' if len(raw)>4096 else
                   'OOM_PROOF_DUPLICATE_KEY' if b',"removed":true}' in raw else
                   'OOM_PROOF_BODY' if raw in (b'[]', b'null') else 'OOM_PROOF_JSON')
        return
    if n in (4, 5):
        original = json.loads(ctx.oom_raw)
        changes = [dict(values={'created': 0, 'running': None}),
                   dict(values={'created': False, 'running': False}), dict(removed=1),
                   dict(productionUnchanged=1)] if n == 4 else [dict(status='OTHER'),
                   dict(removed=False), dict(productionUnchanged=False), dict(extra=True),
                   dict(values={'created': False, 'running': None, 'extra': True})]
        for change in changes:
            refuse(json.dumps({**original, **change}).encode(), 'OOM_PROOF_BODY')
        return
    if n == 6:
        # Reject restrictions before any reservation or effect; no retries involved.
        for value, proof in ((True, False), (False, True), (1, False), (None, False)):
            ctx.profile['sameSchema']['oomLifecycleVerified'] = value
            if proof:
                ctx.profile['sameSchema']['oomLifecycleProof'] = 'oom.json'
            else:
                ctx.profile['sameSchema'].pop('oomLifecycleProof', None)
            ctx.reseal()
            refused = ctx.call('preflight')
            assert refused['status'] == 'OPERATION_HOLD_REQUIRES_OBSERVATION'
            assert refused['safeCode'] in ('SOURCE_PROFILE_FIELDS', 'OOM_PROOF_REQUIRED')
            assert ctx.effects == []
        return
    if n == 8:
        bad = json.loads(ctx.oom_raw)
        bad['productionUnchanged'] = False
        ctx.save('oom.json', bad)
        ctx.reseal()
        refused = ctx.call('preflight')
        assert refused['safeCode'] == 'OOM_PROOF_BODY' and ctx.effects == []
        return
    if n == 9:
        ctx.states[ctx.new_id]['HostConfig']['Privileged'] = True
        refused = ctx.call('preflight')
        assert refused['safeCode'] == 'CONFIGURATION_REPRODUCTION_FAILED' and ctx.effects == []
        return
    if n == 12:
        # A valid proof is insufficient without the accepted preflight receipt.
        assert not (ctx.root/'preflight.json').exists()
        for mode in ('apply', 'recover'):
            result = ctx.call(mode)
            assert result['safeCode'] == 'SOURCE_FILE_LIMIT' and ctx.effects == []
            assert not any((ctx.root/name).exists() for name in ('preflight', 'apply', 'recover'))
        return
    assert ctx.call('preflight')['status'] == 'SAME_SCHEMA_PREFLIGHT_PASS'
    if n == 10:
        ctx.normalize_oom_at_start = False
        result = ctx.call('apply')
        assert result['status'] == 'OPERATION_HOLD_REQUIRES_OBSERVATION'
        assert result['operationStatus'] == 'UNKNOWN' and len(ctx.effects) == 2
        assert not (ctx.root/'apply/pending.json').exists()
        return
    if n == 11:
        ctx.stop_timeout = True
        assert ctx.call('apply')['operationStatus'] == 'UNKNOWN'
        assert ctx.states[ctx.new_id]['State']['Status'] == 'created'
        assert len(ctx.effects) == 1
        returned = ctx.call('recover')
        assert returned['status'] == 'RETURNED_UI_PENDING', returned
        assert len(ctx.effects) == 2
        assert not (ctx.root/'apply/start-intent.json').exists()
        assert ctx.states[ctx.new_id]['State']['Status'] == 'created'
        return
    # O07 exercises all FOUR call sites across the three existing APIs without
    # mocking their implementations, including both historical/live stage checks.
    applied = ctx.call('apply')
    assert applied['status'] == 'BACKEND_SWITCHED_UI_PENDING', applied
    assert ctx.states[ctx.new_id]['HostConfig']['OomKillDisable'] is None
    returned = ctx.call('recover')
    assert returned['status'] == 'RETURNED_UI_PENDING', returned
    assert ctx.states[ctx.old_id]['HostConfig']['OomKillDisable'] is None
    assert len(ctx.effects) == 4
    assert all(result['releaseReady'] is False for result in (applied, returned))
