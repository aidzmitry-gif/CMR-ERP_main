"""Explicit 0194 -> 0195 route after restored-PostgreSQL acceptance.

The installed runner and the earlier image-only extension remain unchanged.
Engine/configuration reproduction is delegated to their existing guards.
"""
import time


def require(value, code):
    if not value:
        raise RuntimeError(code)


def verify_stage(update, runner, before, staged, old_image, new_image, rehearsal,
                 migration_sha, *, oom_lifecycle_verified=False):
    require(rehearsal['status'] == 'REAL_IDENTITY_REHEARSAL_PASS'
            and rehearsal['migrationRoundTrip'] and rehearsal['unsafeDowngradeBlocked']
            and rehearsal['backup']['restoreVerified'], 'RESTORED_POSTGRES_PROOF_REQUIRED')
    require(before['State']['Running'] and before['Image'] == old_image, 'BASE_IMAGE_DRIFT')
    require(not staged['State']['Running'] and staged['Image'] == new_image, 'CANDIDATE_DRIFT')
    update.verify_staged_projection(runner, before, staged,
                                    oom_lifecycle_verified=oom_lifecycle_verified)
    require(runner.inspect(old_image)['Config'] == runner.inspect(new_image)['Config'],
            'IMAGE_CONFIGURATION_CHANGED')
    old, new = runner.image_schema(old_image), runner.image_schema(new_image)
    path = 'migrations/versions/0195_employee_login_accounts.py'
    require(old['heads'] == ['0194'] and new['heads'] == ['0195'], 'SCHEMA_PATH_CHANGED')
    require(set(new['files']) - set(old['files']) == {path}
            and set(old['files']) < set(new['files'])
            and all(new['files'][name] == value for name, value in old['files'].items())
            and new['files'][path] == migration_sha
            and rehearsal['sourceSHAs'][path] == migration_sha,
            'UNAPPROVED_MIGRATION_OR_ENTRYPOINT_CHANGE')


def switch(update, engine, runner, root, before, staged, migration_receipt,
           *, health, schema, oom_lifecycle_verified=False):
    """Caller holds release lease. No retry, implicit return, or database restore."""
    require(migration_receipt['status'] == 'ALEMBIC_0195_APPLIED'
            and migration_receipt['image'] == staged['Image']
            and migration_receipt['backupRestoreVerified'], 'MIGRATION_NOT_ATTESTED')
    require(not (root/'stop-intent.json').exists(), 'ALREADY_STARTED_READ_STATUS')
    current = engine.inspect(before['Id'])
    require(current['State']['Running']
            and current['State']['StartedAt'] == before['State']['StartedAt']
            and runner.projection(current) == runner.projection(before), 'LIVE_CONFIGURATION_DRIFT')
    require(schema(before['Id']) == ['0195'], 'MIGRATION_NOT_OBSERVED')
    candidate = engine.inspect(staged['Id'])
    require(candidate['Image'] == staged['Image'] and not candidate['State']['Running'],
            'STAGED_DRIFT')
    update.verify_staged_projection(runner, before, candidate,
                                    oom_lifecycle_verified=oom_lifecycle_verified)
    update.exclusive(root/'stop-intent.json', {'id': before['Id'], 'status': 'ATTEMPTED_UNKNOWN'})
    engine.request('POST', '/containers/'+before['Id']+'/stop?t=10')
    require(not engine.inspect(before['Id'])['State']['Running'], 'BASE_STOP_UNKNOWN')
    update.exclusive(root/'stop-confirmed.json', {'id': before['Id'], 'stopped': True})
    update.exclusive(root/'start-intent.json', {'id': candidate['Id'], 'status': 'ATTEMPTED_UNKNOWN'})
    engine.request('POST', '/containers/'+candidate['Id']+'/start')
    require(engine.inspect(candidate['Id'])['State']['Running'], 'CANDIDATE_START_UNKNOWN')
    update.exclusive(root/'start-confirmed.json', {'id': candidate['Id'], 'running': True})
    deadline = time.monotonic()+60
    while time.monotonic() < deadline:
        active = engine.inspect(candidate['Id'])
        require(runner.projection(active) == runner.projection(before), 'POST_CONFIGURATION_DRIFT')
        if active['State']['Running'] and health():
            require(schema(candidate['Id']) == ['0195'], 'POST_SCHEMA_CHANGED')
            return active
        time.sleep(.5)
    raise RuntimeError('HEALTH_TIMEOUT_EXPLICIT_COMPATIBLE_RETURN_REQUIRED')



def verify_same_schema_stage(update, runner, before, staged, seal, *,
                             oom_lifecycle_verified=False):
    """Validate an owned, never-started 0204 image replacement without effects.

    The caller seals the private release root, snapshots and provenance, holds
    the existing lease, and separately admits the runtime operation. Only the
    two existing package/source image labels may change. Runtime labels stay
    exactly as reproduced from the retained base container.
    """
    import re

    fields = {'oldImage', 'newImage', 'oldConfigSHA', 'newConfigSHA',
              'oldCheckpoint', 'newCheckpoint', 'oldSourceSHA256',
              'newSourceSHA256', 'schemaHeads'}
    require(isinstance(seal, dict) and set(seal) == fields, 'SAME_SCHEMA_SEAL_FIELDS')
    for key in fields - {'schemaHeads'}:
        length = 40 if key.endswith('Checkpoint') else 64
        pattern = r'sha256:[a-f0-9]{64}' if key.endswith('Image') else '[a-f0-9]{'+str(length)+'}'
        require(isinstance(seal[key], str) and re.fullmatch(pattern, seal[key]),
                'SAME_SCHEMA_SEAL_VALUE')
    require(seal['schemaHeads'] == ['0204'], 'SAME_SCHEMA_HEAD_REQUIRED')
    old_image, new_image = seal['oldImage'], seal['newImage']
    require(old_image != new_image, 'DISTINCT_IMAGE_REQUIRED')
    require(type(oom_lifecycle_verified) is bool, 'OOM_ATTESTATION_BOOLEAN_REQUIRED')
    require(all(isinstance(info['Id'], str) and re.fullmatch('[a-f0-9]{64}', info['Id'])
                for info in (before, staged)) and before['Id'] != staged['Id'],
            'DISTINCT_EXACT_CONTAINER_IDS_REQUIRED')
    require(before['HostConfig']['AutoRemove'] is False
            and staged['HostConfig']['AutoRemove'] is False, 'ROLLBACK_MUST_BE_RETAINED')
    base_state, stage_state = before['State'], staged['State']
    require(before['Image'] == old_image and base_state['Running'] is True
            and base_state['Status'] == 'running' and type(base_state['Pid']) is int
            and base_state['Pid'] > 0 and not base_state['Paused']
            and not base_state['Restarting'], 'BASE_IMAGE_OR_STATE_DRIFT')
    require(staged['Image'] == new_image and staged['Config']['Image'] == new_image
            and stage_state['Running'] is False and stage_state['Status'] == 'created'
            and stage_state['Pid'] == 0 and stage_state['ExitCode'] == 0
            and stage_state['OOMKilled'] is False and not stage_state['Paused']
            and not stage_state['Restarting'] and staged['RestartCount'] == 0
            and isinstance(stage_state['StartedAt'], str)
            and stage_state['StartedAt'].startswith('0001-01-01T00:00:00'),
            'CANDIDATE_NOT_NEVER_STARTED')
    update.verify_staged_projection(runner, before, staged,
                                    oom_lifecycle_verified=oom_lifecycle_verified)
    old, new = runner.inspect(old_image), runner.inspect(new_image)
    require(old['Id'] == old_image and new['Id'] == new_image, 'IMAGE_ID_DRIFT')
    require(runner.digest(old['Config']) == seal['oldConfigSHA']
            and runner.digest(new['Config']) == seal['newConfigSHA'], 'IMAGE_CONFIG_SEAL_DRIFT')
    require({k: v for k, v in old['Config'].items() if k != 'Labels'}
            == {k: v for k, v in new['Config'].items() if k != 'Labels'},
            'IMAGE_NONLABEL_CONFIGURATION_CHANGED')
    old_labels, new_labels = old['Config']['Labels'], new['Config']['Labels']
    allowed = {'crm-rel-001-source', 'crm-rel-001-package'}
    require(isinstance(old_labels, dict) and isinstance(new_labels, dict)
            and set(old_labels) == set(new_labels) and allowed <= set(old_labels)
            and {key for key in old_labels if old_labels[key] != new_labels[key]} == allowed,
            'UNAPPROVED_IMAGE_LABEL_CHANGE')
    require(old_labels['crm-rel-001-source'] == seal['oldSourceSHA256']
            and new_labels['crm-rel-001-source'] == seal['newSourceSHA256']
            and old_labels['crm-rel-001-package'] == seal['oldCheckpoint']
            and new_labels['crm-rel-001-package'] == seal['newCheckpoint'],
            'IMAGE_PROVENANCE_BINDING_CHANGED')
    old_schema, new_schema = runner.image_schema(old_image), runner.image_schema(new_image)
    require(old_schema == new_schema and old_schema['heads'] == ['0204'],
            'SAME_SCHEMA_MIGRATION_OR_ENTRYPOINT_CHANGED')


def switch_same_schema(update, engine, runner, root, before, staged, seal, *,
                       health, schema, oom_lifecycle_verified=False):
    """Compose existing Engine/intent guards; retain both containers on failure.

    Caller holds the release lease and owns sealed root/snapshots. Callbacks
    receive the exact CID and must have hard transport limits (health <=3s,
    schema <=15s). The 60s budget also rejects late positive callback results.
    This function grants no deployment authority or UI/final receipt acceptance.
    Lost replies retain UNKNOWN intents: observe, never retry implicitly.
    """
    markers = ('stop-intent.json', 'stop-confirmed.json',
               'start-intent.json', 'start-confirmed.json')
    require(not any((root / name).exists() or (root / name).is_symlink()
                    for name in markers), 'ALREADY_STARTED_READ_STATUS')
    # Freeze acceptance bindings before any externally supplied callback/effect.
    old_id, new_id = before['Id'], staged['Id']
    old_image, new_image = before['Image'], staged['Image']
    old_name, new_name = before['Name'], staged['Name']
    old_started = before['State']['StartedAt']
    stage_started = staged['State']['StartedAt']
    old_restarts = before['RestartCount']
    expected = runner.digest(runner.projection(before))
    expected_stage = runner.digest(runner.projection(staged))
    expected_heads = ('0204',)

    def identity(info, cid, image, name, projection):
        require(info['Id'] == cid and info['Image'] == image and info['Name'] == name
                and runner.digest(runner.projection(info)) == projection,
                'CONTAINER_IDENTITY_OR_CONFIGURATION_DRIFT')
        require(cid != new_id or info['Config']['Image'] == new_image,
                'CANDIDATE_CONFIG_IMAGE_DRIFT')

    def running(info):
        state = info['State']
        require(state['Running'] is True and state['Status'] == 'running'
                and type(state['Pid']) is int and state['Pid'] > 0
                and not state['Paused'] and not state['Restarting']
                and state['OOMKilled'] is False
                and isinstance(state['StartedAt'], str)
                and not state['StartedAt'].startswith('0001-01-01'),
                'RUNNING_STATE_NOT_CONFIRMED')

    def stopped(info):
        state = info['State']
        identity(info, old_id, old_image, old_name, expected)
        require(state['Running'] is False and state['Status'] == 'exited'
                and state['Pid'] == 0 and not state['Paused']
                and not state['Restarting'] and state['OOMKilled'] is False
                and info['RestartCount'] == old_restarts, 'BASE_STOP_UNKNOWN')

    current, candidate = engine.inspect(old_id), engine.inspect(new_id)
    identity(current, old_id, old_image, old_name, expected)
    identity(candidate, new_id, new_image, new_name, expected_stage)
    running(current)
    require(current['State']['StartedAt'] == old_started, 'LIVE_START_IDENTITY_DRIFT')
    verify_same_schema_stage(update, runner, current, candidate, seal,
                             oom_lifecycle_verified=oom_lifecycle_verified)
    require(tuple(schema(old_id)) == expected_heads, 'LIVE_SAME_SCHEMA_NOT_OBSERVED')
    # Re-read both after the read-only callback, before creating any intent.
    current, candidate = engine.inspect(old_id), engine.inspect(new_id)
    identity(current, old_id, old_image, old_name, expected)
    identity(candidate, new_id, new_image, new_name, expected_stage)
    running(current)
    require(current['State']['StartedAt'] == old_started, 'LIVE_START_IDENTITY_DRIFT')
    state = candidate['State']
    require(state['Running'] is False and state['Status'] == 'created'
            and state['Pid'] == 0 and state['ExitCode'] == 0
            and state['OOMKilled'] is False and not state['Paused']
            and not state['Restarting'] and candidate['RestartCount'] == 0
            and state['StartedAt'] == stage_started, 'STAGED_STATE_DRIFT')
    update.exclusive(root / 'stop-intent.json', {'id': old_id, 'status': 'ATTEMPTED_UNKNOWN'})
    engine.request('POST', '/containers/' + old_id + '/stop?t=10')
    stopped(engine.inspect(old_id))
    update.exclusive(root / 'stop-confirmed.json', {'id': old_id, 'stopped': True})
    update.exclusive(root / 'start-intent.json', {'id': new_id, 'status': 'ATTEMPTED_UNKNOWN'})
    deadline = time.monotonic() + 60
    engine.request('POST', '/containers/' + new_id + '/start')
    require(time.monotonic() < deadline, 'HEALTH_TIMEOUT_EXPLICIT_RETURN_REQUIRED')
    active = engine.inspect(new_id)
    identity(active, new_id, new_image, new_name, expected)
    running(active)
    require(active['RestartCount'] == 0, 'CANDIDATE_RESTARTED')
    new_started = active['State']['StartedAt']
    require(time.monotonic() < deadline, 'HEALTH_TIMEOUT_EXPLICIT_RETURN_REQUIRED')
    update.exclusive(root / 'start-confirmed.json', {'id': new_id, 'running': True})
    while time.monotonic() < deadline:
        active = engine.inspect(new_id)
        identity(active, new_id, new_image, new_name, expected)
        running(active)
        require(active['State']['StartedAt'] == new_started and active['RestartCount'] == 0,
                'CANDIDATE_RESTARTED')
        stopped(engine.inspect(old_id))
        require(time.monotonic() < deadline, 'HEALTH_TIMEOUT_EXPLICIT_RETURN_REQUIRED')
        healthy = health(new_id)
        require(time.monotonic() < deadline, 'HEALTH_TIMEOUT_EXPLICIT_RETURN_REQUIRED')
        if healthy is True:
            heads = tuple(schema(new_id))
            require(time.monotonic() < deadline, 'HEALTH_TIMEOUT_EXPLICIT_RETURN_REQUIRED')
            require(heads == expected_heads, 'POST_SCHEMA_CHANGED')
            # Callbacks can take time: final acceptance always uses fresh states.
            active = engine.inspect(new_id)
            identity(active, new_id, new_image, new_name, expected)
            running(active)
            require(active['State']['StartedAt'] == new_started and active['RestartCount'] == 0,
                    'CANDIDATE_RESTARTED')
            stopped(engine.inspect(old_id))
            require(time.monotonic() < deadline, 'HEALTH_TIMEOUT_EXPLICIT_RETURN_REQUIRED')
            return active
        time.sleep(.5)
    raise RuntimeError('HEALTH_TIMEOUT_EXPLICIT_RETURN_REQUIRED')



def return_same_schema(update, engine, runner, root, before, staged, observed, seal, *,
                       health, schema, oom_lifecycle_verified=False):
    """Return to the retained 0204 container without database/config changes.

    Caller holds the existing lease, owns this release root, and seals actual
    ORIGINAL pre-forward snapshots plus a fresh candidate observation. They are
    never relabelled as current state: actual return states are inspected below.
    Caller separately admits the return, proves code/data compatibility, and
    supplies CID-bound health <=3s and PG-bound schema <=15s callbacks (schema
    must work while the app is stopped). Native acceptance remains separate.
    UNKNOWN replies retain exclusive markers; never retry or restore a database.
    """
    import json

    return_markers = ('return-stop-intent.json', 'return-stop-confirmed.json',
                      'return-start-intent.json', 'return-start-confirmed.json')

    def unused_return():
        require(not any((root / name).exists() or (root / name).is_symlink()
                        for name in return_markers), 'ALREADY_RETURNING_READ_STATUS')

    unused_return()
    # These are sealed historical snapshots, not fabricated running/created flags.
    verify_same_schema_stage(update, runner, before, staged, seal,
                             oom_lifecycle_verified=oom_lifecycle_verified)
    old_id, new_id = before['Id'], staged['Id']
    old_image, new_image = before['Image'], staged['Image']
    old_name, new_name = before['Name'], staged['Name']
    old_config_image = before['Config']['Image']
    old_started, stage_started = before['State']['StartedAt'], staged['State']['StartedAt']
    old_restarts = before['RestartCount']
    expected_old = runner.digest(runner.projection(before))
    mode = observed['State']['Status']
    observed_started = observed['State']['StartedAt']
    require(mode in ('running', 'exited', 'created'), 'RETURN_CANDIDATE_PHASE_UNKNOWN')
    expected_new = (runner.digest(runner.projection(staged))
                    if mode == 'created' else expected_old)
    expected_heads = ('0204',)

    def signature(info):
        state = info['State']
        return tuple(state.get(k) for k in (
            'Running', 'Status', 'Pid', 'StartedAt', 'FinishedAt', 'ExitCode',
            'OOMKilled', 'Paused', 'Restarting')) + (info['RestartCount'],)

    observed_signature = signature(observed)

    def identity(info, cid, image, name, projection, config_image):
        require(info['Id'] == cid and info['Image'] == image and info['Name'] == name
                and info['Config']['Image'] == config_image
                and runner.digest(runner.projection(info)) == projection,
                'RETURN_IDENTITY_OR_CONFIGURATION_DRIFT')
        policy = info['HostConfig'].get('RestartPolicy')
        require(policy == {'Name': 'no', 'MaximumRetryCount': 0}
                and type(policy.get('MaximumRetryCount')) is int
                and info['HostConfig']['AutoRemove'] is False,
                'RETURN_REQUIRES_RETAINED_NO_RESTART_CONTAINERS')

    def base_stopped(info):
        identity(info, old_id, old_image, old_name, expected_old, old_config_image)
        state = info['State']
        require(state['Running'] is False and state['Status'] == 'exited'
                and type(state['Pid']) is int and state['Pid'] == 0
                and state['Paused'] is False and state['Restarting'] is False
                and state['OOMKilled'] is False and state['StartedAt'] == old_started
                and info['RestartCount'] == old_restarts, 'RETAINED_BASE_NOT_STOPPED')

    def candidate_before(info):
        identity(info, new_id, new_image, new_name, expected_new, new_image)
        require(signature(info) == observed_signature, 'RETURN_OBSERVATION_DRIFT')
        state = info['State']
        require(state['Status'] == mode and state['Paused'] is False
                and state['Restarting'] is False and type(state['Pid']) is int
                and type(state['ExitCode']) is int and type(state['OOMKilled']) is bool
                and type(info['RestartCount']) is int and info['RestartCount'] == 0
                and isinstance(state['StartedAt'], str), 'RETURN_CANDIDATE_STATE_UNKNOWN')
        if mode == 'running':
            require(state['Running'] is True and state['Pid'] > 0
                    and not state['StartedAt'].startswith('0001-01-01')
                    and state['OOMKilled'] is False, 'RETURN_RUNNING_STATE_UNKNOWN')
        else:
            require(state['Running'] is False and state['Pid'] == 0,
                    'RETURN_INACTIVE_STATE_UNKNOWN')
            if mode == 'created':
                require(state['StartedAt'] == stage_started and state['ExitCode'] == 0
                        and state['OOMKilled'] is False, 'RETURN_CREATED_STATE_UNKNOWN')
            else:
                require(not state['StartedAt'].startswith('0001-01-01'),
                        'RETURN_EXITED_START_UNKNOWN')

    def forward_lineage():
        expected = {
            'stop-intent.json': {'id': old_id, 'status': 'ATTEMPTED_UNKNOWN'},
            'stop-confirmed.json': {'id': old_id, 'stopped': True},
            'start-intent.json': {'id': new_id, 'status': 'ATTEMPTED_UNKNOWN'},
            'start-confirmed.json': {'id': new_id, 'running': True},
        }
        records = {}
        for name, wanted in expected.items():
            path = root / name
            require(not path.is_symlink(), 'RETURN_FORWARD_LINEAGE_INVALID')
            if not path.exists():
                records[name] = None
                continue
            require(path.is_file() and path.stat().st_size <= 4096,
                    'RETURN_FORWARD_LINEAGE_INVALID')
            with path.open('rb') as stream:
                raw = stream.read(4097)
            require(len(raw) <= 4096, 'RETURN_FORWARD_LINEAGE_INVALID')
            try:
                record = json.loads(raw)
            except (ValueError, UnicodeError) as error:
                raise RuntimeError('RETURN_FORWARD_LINEAGE_INVALID') from error
            require(isinstance(record, dict) and record == wanted
                    and all(type(record[k]) is type(v) for k, v in wanted.items()),
                    'RETURN_FORWARD_LINEAGE_INVALID')
            records[name] = record
        require(records['stop-intent.json'] is not None, 'RETURN_FORWARD_STOP_INTENT_REQUIRED')
        require(records['start-intent.json'] is None
                or records['stop-confirmed.json'] is not None,
                'RETURN_FORWARD_CAUSAL_ORDER_INVALID')
        require(records['start-confirmed.json'] is None
                or (records['start-intent.json'] is not None
                    and records['stop-confirmed.json'] is not None),
                'RETURN_FORWARD_CAUSAL_ORDER_INVALID')
        if mode == 'created':
            require(records['start-intent.json'] is None
                    and records['start-confirmed.json'] is None,
                    'RETURN_CREATED_START_UNKNOWN_OBSERVE_REQUIRED')
        else:
            require(records['start-intent.json'] is not None,
                    'RETURN_FORWARD_START_INTENT_REQUIRED')
        return runner.digest(records)

    candidate_before(observed)
    lineage = forward_lineage()
    base_stopped(engine.inspect(old_id))
    candidate_before(engine.inspect(new_id))
    require(tuple(schema(old_id)) == expected_heads, 'RETURN_PRE_SCHEMA_CHANGED')
    # Re-read after the callback before recording any new consequential intent.
    base_stopped(engine.inspect(old_id))
    candidate_before(engine.inspect(new_id))
    require(forward_lineage() == lineage, 'RETURN_FORWARD_LINEAGE_CHANGED')
    unused_return()
    update.exclusive(root / 'return-stop-intent.json', {
        'id': new_id, 'status': 'ATTEMPTED_UNKNOWN' if mode == 'running' else 'OBSERVED_INACTIVE',
        'action': 'STOP' if mode == 'running' else 'OBSERVE_INACTIVE'})
    if mode == 'running':
        engine.request('POST', '/containers/' + new_id + '/stop?t=10')
    inactive = engine.inspect(new_id)
    identity(inactive, new_id, new_image, new_name, expected_new, new_image)
    state = inactive['State']
    require(state['Running'] is False and state['Pid'] == 0
            and state['Status'] == ('exited' if mode == 'running' else mode)
            and state['StartedAt'] == observed_started
            and state['Paused'] is False and state['Restarting'] is False
            and inactive['RestartCount'] == 0, 'RETURN_CANDIDATE_STOP_UNKNOWN')
    if mode != 'running':
        require(signature(inactive) == observed_signature, 'RETURN_INACTIVE_STATE_DRIFT')
    inactive_signature = signature(inactive)
    base_stopped(engine.inspect(old_id))
    update.exclusive(root / 'return-stop-confirmed.json', {
        'id': new_id, 'stopped': True,
        'method': 'POST' if mode == 'running' else 'OBSERVED_NO_RESTART'})
    update.exclusive(root / 'return-start-intent.json', {'id': old_id, 'status': 'ATTEMPTED_UNKNOWN'})
    deadline = time.monotonic() + 60
    engine.request('POST', '/containers/' + old_id + '/start')
    require(time.monotonic() < deadline, 'RETURN_HEALTH_TIMEOUT_OBSERVE_REQUIRED')

    def base_running(info):
        identity(info, old_id, old_image, old_name, expected_old, old_config_image)
        state = info['State']
        require(state['Running'] is True and state['Status'] == 'running'
                and type(state['Pid']) is int and state['Pid'] > 0
                and state['Paused'] is False and state['Restarting'] is False
                and state['OOMKilled'] is False and info['RestartCount'] == 0
                and isinstance(state['StartedAt'], str) and state['StartedAt'] != old_started
                and not state['StartedAt'].startswith('0001-01-01'), 'RETURN_BASE_START_UNKNOWN')

    def candidate_inactive(info):
        identity(info, new_id, new_image, new_name, expected_new, new_image)
        require(signature(info) == inactive_signature, 'RETURN_CANDIDATE_RESTART_OR_DRIFT')

    active = engine.inspect(old_id)
    base_running(active)
    returned_start = active['State']['StartedAt']
    require(time.monotonic() < deadline, 'RETURN_HEALTH_TIMEOUT_OBSERVE_REQUIRED')
    update.exclusive(root / 'return-start-confirmed.json', {'id': old_id, 'running': True})
    while time.monotonic() < deadline:
        active = engine.inspect(old_id)
        base_running(active)
        require(active['State']['StartedAt'] == returned_start, 'RETURN_BASE_RESTARTED')
        candidate_inactive(engine.inspect(new_id))
        require(time.monotonic() < deadline, 'RETURN_HEALTH_TIMEOUT_OBSERVE_REQUIRED')
        healthy = health(old_id)
        require(time.monotonic() < deadline, 'RETURN_HEALTH_TIMEOUT_OBSERVE_REQUIRED')
        if healthy is True:
            heads = tuple(schema(old_id))
            require(time.monotonic() < deadline, 'RETURN_HEALTH_TIMEOUT_OBSERVE_REQUIRED')
            require(heads == expected_heads, 'RETURN_POST_SCHEMA_CHANGED')
            active = engine.inspect(old_id)
            base_running(active)
            require(active['State']['StartedAt'] == returned_start, 'RETURN_BASE_RESTARTED')
            candidate_inactive(engine.inspect(new_id))
            require(time.monotonic() < deadline, 'RETURN_HEALTH_TIMEOUT_OBSERVE_REQUIRED')
            return active
        time.sleep(.5)
    raise RuntimeError('RETURN_HEALTH_TIMEOUT_OBSERVE_REQUIRED')


def same_schema_callbacks(binding):
    """Build fixed local probes; caller separately seals PG/app/config and lease.

    Health uses the exact app CID. Schema reads the sealed PG CID and works
    while either app is stopped. No commands run during construction. Native
    binary capabilities and app -> PG/database/user binding require preflight.
    Transport limits are 3/15s with late-result refusal; arbitrary kernel
    stalls cannot be bounded here. A lost Docker reply leaves remote exec
    UNKNOWN even though already-started probes have inner 2/12s limits.
    This helper supplies no deployment, retry, cleanup or receipt authority.
    """
    import re
    import subprocess

    require(isinstance(binding, dict)
            and set(binding) == {'appIDs', 'pgID', 'database', 'appUser'},
            'PROBE_BINDING_FIELDS')
    app_ids, pg_id = binding['appIDs'], binding['pgID']
    database, app_user = binding['database'], binding['appUser']
    require(isinstance(app_ids, (list, tuple)) and len(app_ids) == 2
            and all(isinstance(cid, str) and re.fullmatch('[a-f0-9]{64}', cid)
                    for cid in (*app_ids, pg_id))
            and len(set((*app_ids, pg_id))) == 3, 'PROBE_EXACT_DISTINCT_IDS')
    app_ids = tuple(app_ids)
    require(isinstance(database, str)
            and re.fullmatch('[A-Za-z_][A-Za-z_0-9]{0,62}', database)
            and database.lower() not in ('postgres', 'template0', 'template1'),
            'PROBE_DATABASE_SCOPE')
    require(isinstance(app_user, str)
            and re.fullmatch('[0-9]{1,10}:[0-9]{1,10}', app_user),
            'PROBE_NUMERIC_APP_USER')

    def scope(cid):
        require(isinstance(cid, str) and cid in app_ids, 'PROBE_APP_OUT_OF_SCOPE')

    def probe(arguments, limit):
        started = time.monotonic()
        try:
            result = subprocess.run(
                ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock',
                 'exec', *arguments],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, shell=False, check=False,
                env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'HOME': '/nonexistent'},
                timeout=limit)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError('PROBE_UNAVAILABLE_OR_TIMEOUT') from None
        require(time.monotonic() - started < limit, 'PROBE_LATE_RESULT')
        require(result.returncode == 0, 'PROBE_COMMAND_FAILED_REDACTED')
        raw = result.stdout
        require(isinstance(raw, bytes) and len(raw) <= 1024, 'PROBE_OUTPUT_LIMIT')
        return raw, started

    health_program = '''import signal
signal.signal(signal.SIGALRM, signal.SIG_DFL)
signal.setitimer(signal.ITIMER_REAL, 2)
import http.client
connection = None
healthy = False
try:
    connection = http.client.HTTPConnection('127.0.0.1', 8000, timeout=1.5)
    connection.request('GET', '/health')
    healthy = connection.getresponse().status == 200
except (OSError, http.client.HTTPException):
    pass
finally:
    if connection is not None:
        connection.close()
print('HEALTHY' if healthy else 'UNHEALTHY')
'''

    def health(cid):
        scope(cid)
        raw, started = probe(['--user', app_user, cid, 'python', '-I', '-S', '-B',
                              '-c', health_program], 3)
        require(raw in (b'HEALTHY\n', b'UNHEALTHY\n'), 'HEALTH_PROBE_PROTOCOL')
        require(time.monotonic() - started < 3, 'PROBE_LATE_RESULT')
        return raw == b'HEALTHY\n'

    def schema(cid):
        scope(cid)
        args = [pg_id, '/usr/bin/env', '-i',
                'PATH=/usr/local/bin:/usr/bin:/bin:/usr/lib/postgresql/16/bin',
                'LC_ALL=C', 'PGCONNECT_TIMEOUT=2',
                'PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=10000 -c lock_timeout=2000',
                '/usr/bin/timeout', '--signal=KILL', '12s', 'psql',
                '-X', '-w', '-Atq', '-h', '/var/run/postgresql', '-U', 'aios',
                '-d', database, '--set=ON_ERROR_STOP=1']
        for sql in ('BEGIN READ ONLY', 'SET LOCAL statement_timeout=10000',
                    'SET LOCAL lock_timeout=2000',
                    'SELECT version_num FROM public.alembic_version ORDER BY version_num LIMIT 3',
                    'ROLLBACK'):
            args.extend(('-c', sql))
        raw, started = probe(args, 15)
        try:
            heads = raw.decode('ascii').splitlines()
        except UnicodeError:
            raise RuntimeError('SCHEMA_PROBE_PROTOCOL') from None
        require(len(heads) <= 2 and heads == sorted(set(heads))
                and all(re.fullmatch('[a-z0-9_]{1,32}', head) for head in heads)
                and (not raw or raw == ('\n'.join(heads) + '\n').encode('ascii')),
                'SCHEMA_PROBE_PROTOCOL')
        require(time.monotonic() - started < 15, 'PROBE_LATE_RESULT')
        return heads

    return health, schema


def cached_image_schema_runner(base, artifacts):
    """Reuse approved immutable image proofs, keeping image inspection fresh.

    Expected pins must come from the separately approved sealed release, not
    be computed from unapproved input. The native verifier already checked
    every image file against its source manifest and evaluated the Alembic
    head. This facade derives precisely the installed image_schema projection.
    Missing images never fall back to another Docker probe. The existing
    stage verifier still checks fresh image IDs, Config, labels and snapshots.
    No commands run at construction, and this grants no release authority.
    """
    import copy
    import hashlib
    import json
    import re
    from pathlib import PurePosixPath
    from types import SimpleNamespace

    require(isinstance(artifacts, dict) and 1 <= len(artifacts) <= 2,
            'IMAGE_SCHEMA_CACHE_ARTIFACTS')
    fields = {'manifestBytes', 'manifestSHA256', 'receiptBytes',
              'receiptSHA256', 'sourceSHA256', 'checkpoint'}

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'IMAGE_SCHEMA_CACHE_DUPLICATE_KEY')
            result[key] = value
        return result

    def load(raw, wanted, maximum):
        require(type(raw) is bytes and len(raw) <= maximum,
                'IMAGE_SCHEMA_CACHE_BYTES_LIMIT')
        require(hashlib.sha256(raw).hexdigest() == wanted, 'IMAGE_SCHEMA_CACHE_HASH')
        try:
            return json.loads(raw, object_pairs_hook=unique_object)
        except (ValueError, UnicodeError):
            raise RuntimeError('IMAGE_SCHEMA_CACHE_JSON') from None

    schemas = {}
    for image, artifact in artifacts.items():
        require(isinstance(image, str) and re.fullmatch('sha256:[a-f0-9]{64}', image),
                'IMAGE_SCHEMA_CACHE_IMAGE_ID')
        require(isinstance(artifact, dict) and set(artifact) == fields,
                'IMAGE_SCHEMA_CACHE_FIELDS')
        for key in fields - {'manifestBytes', 'receiptBytes'}:
            length = 40 if key == 'checkpoint' else 64
            require(isinstance(artifact[key], str)
                    and re.fullmatch('[a-f0-9]{' + str(length) + '}', artifact[key]),
                    'IMAGE_SCHEMA_CACHE_PIN')
        manifest = load(artifact['manifestBytes'], artifact['manifestSHA256'], 2 * 1024 * 1024)
        receipt = load(artifact['receiptBytes'], artifact['receiptSHA256'], 16384)
        require(isinstance(manifest, dict), 'IMAGE_SCHEMA_CACHE_MANIFEST')
        require(manifest.get('package_checkpoint') == artifact['checkpoint']
                and manifest.get('head') == '0204', 'IMAGE_SCHEMA_CACHE_MANIFEST_BINDING')
        files = manifest.get('files')
        require(isinstance(files, dict) and 1 <= len(files) <= 10000,
                'IMAGE_SCHEMA_CACHE_FILES')
        for name, value in files.items():
            require(isinstance(name, str) and name not in ('', '.')
                    and '\\' not in name and ':' not in name
                    and not any(ord(char) < 32 or ord(char) == 127 for char in name)
                    and not PurePosixPath(name).is_absolute()
                    and '..' not in PurePosixPath(name).parts
                    and str(PurePosixPath(name)) == name, 'IMAGE_SCHEMA_CACHE_PATH')
            require(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value),
                    'IMAGE_SCHEMA_CACHE_FILE_HASH')
        source = hashlib.sha256(json.dumps(
            files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        require(source == artifact['sourceSHA256'], 'IMAGE_SCHEMA_CACHE_SOURCE_BINDING')
        require(isinstance(receipt, dict)
                and receipt.get('status') == 'IMMUTABLE_BACKEND_IMAGE_VERIFIED'
                and receipt.get('image') == image
                and receipt.get('source_sha256') == source
                and receipt.get('package_checkpoint') == artifact['checkpoint']
                and receipt.get('head') == '0204'
                and type(receipt.get('production_changes')) is int
                and receipt['production_changes'] == 0
                and receipt.get('release_ready') is False
                and type(receipt.get('native_pdf_bytes')) is int
                and receipt['native_pdf_bytes'] > 0, 'IMAGE_SCHEMA_CACHE_NATIVE_PROOF')
        schema_files = {name: value for name, value in files.items()
                        if name in ('alembic.ini', 'docker/app-entrypoint.sh')
                        or (name.startswith('migrations/') and name.endswith('.py'))}
        require({'alembic.ini', 'docker/app-entrypoint.sh'} <= set(schema_files)
                and any(name.startswith('migrations/versions/') and name.endswith('.py')
                        for name in schema_files), 'IMAGE_SCHEMA_CACHE_SCHEMA_FILES')
        schemas[image] = {'heads': ['0204'], 'files': schema_files}

    require(all(callable(getattr(base, name, None)) for name in
                ('inspect', 'projection', 'digest')), 'IMAGE_SCHEMA_CACHE_BASE')
    base_inspect, projection, digest = base.inspect, base.projection, base.digest

    def scoped(image):
        require(isinstance(image, str) and image in schemas, 'IMAGE_SCHEMA_CACHE_SCOPE')

    def inspect(image):
        scoped(image)
        info = base_inspect(image)
        require(isinstance(info, dict) and info.get('Id') == image,
                'IMAGE_SCHEMA_CACHE_INSPECT_ID')
        return info

    def image_schema(image):
        scoped(image)
        return copy.deepcopy(schemas[image])

    return SimpleNamespace(inspect=inspect, projection=projection,
                           digest=digest, image_schema=image_schema)


def extend_same_schema_entrypoint(original):
    """Render the existing sealed driver; its legacy body remains unchanged."""
    import hashlib
    require(type(original) is bytes and hashlib.sha256(original).hexdigest()
            == '7a8b047dbe202dd8de18947d881378e41edc4abe311abc8f11055ac19bbe8567',
            'ACCEPTED_ENTRYPOINT_CHANGED')
    marker = b"flow=module('operation',ROOT/'operation.py');adapter_module=module('current_adapter',ROOT/'adapter.py')"
    branch = b"""if 'route' in p:
 require(p['route']=='SAME_SCHEMA_0204','UNKNOWN_RELEASE_ROUTE')
 require({'compatible_schema_image.py','fresh_backend_image.py'}<=set(manifest['files']),'UNSEALED_ROUTE_CODE')
 same=module('same_schema_route',ROOT/'compatible_schema_image.py')
 update=module('same_schema_update',ROOT/'fresh_backend_image.py')
 result=same.run_same_schema_current(ROOT,p,manifest,sys.argv[1],leaves,k,r,update,helper_ns['Engine']())
 print(json.dumps(result));raise SystemExit(0)
"""
    require(original.count(marker) == 1, 'ACCEPTED_ENTRYPOINT_SHAPE')
    return original.replace(marker, branch + marker, 1)


def same_schema_configuration_probe(binding):
    """Settings-only exact-CID probe; no application startup or SQL.

    This checks normal construction, not privileged resident-memory injection.
    Inner 4s/outer 5s limits reject late results; lost exec replies stay unknown.
    Stopped apps are never started for diagnostics. No configuration is printed.
    """
    import re
    import subprocess
    require(isinstance(binding, dict) and set(binding) ==
            {'appIDs', 'appUser', 'databaseURLSHA256'}, 'CONFIGURATION_PROBE_BINDING')
    ids, user, sha = binding['appIDs'], binding['appUser'], binding['databaseURLSHA256']
    require(isinstance(ids, (list, tuple)) and len(ids) == 2
            and all(isinstance(cid, str) and re.fullmatch('[a-f0-9]{64}', cid) for cid in ids)
            and len(set(ids)) == 2 and isinstance(user, str)
            and re.fullmatch('[0-9]{1,10}:[0-9]{1,10}', user)
            and isinstance(sha, str) and re.fullmatch('[a-f0-9]{64}', sha),
            'CONFIGURATION_PROBE_BINDING')
    ids = tuple(ids)
    program = '''import signal
signal.signal(signal.SIGALRM, signal.SIG_DFL)
signal.setitimer(signal.ITIMER_REAL, 4)
import hashlib,sys
from pathlib import Path
expected = {'config/__init__.py': 'a79e374991bf7d0525594ebdde0691ee21502027a15bb3e8443835be45ef860a',
            'config/settings.py': '5712caeda80cc397bfd995141f29cc5c248835718c0dc0075796fc0c43b167a4'}
assert all(not (Path('/app')/name).is_symlink() and
           hashlib.sha256((Path('/app')/name).read_bytes()).hexdigest()==value
           for name,value in expected.items())
sys.path.insert(0, '/app')
from config.settings import get_settings
settings = get_settings()
assert settings.ai_enabled is False and not settings.llm_base_url.strip()
assert hashlib.sha256(str(settings.database_url).encode()).hexdigest() == URL_SHA
print('BINDING_OK')
'''.replace('URL_SHA', repr(sha))

    def check(cid):
        require(isinstance(cid, str) and cid in ids, 'CONFIGURATION_PROBE_SCOPE')
        started = time.monotonic()
        try:
            result = subprocess.run(
                ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'exec',
                 '--user', user, cid, 'python', '-I', '-B', '-c', program],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                shell=False, check=False, timeout=5,
                env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'HOME': '/nonexistent'})
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError('CONFIGURATION_PROBE_UNAVAILABLE') from None
        require(time.monotonic() - started < 5, 'CONFIGURATION_PROBE_LATE')
        require(result.returncode == 0 and result.stdout == b'BINDING_OK\n', 'CONFIGURATION_PROBE_FAILED')
        return True
    return check


def run_same_schema_current(root, profile, manifest, mode, leaves, core, runner, update, engine):
    """Mechanical 0204 branch of the existing driver, under its existing lease.

    Root approval of exact manifest/CLI mode is external. Future packages still
    need full CI, native image, compatibility and current frontend acceptance.
    Sealed profile restrictions grant no permission. OOM relaxation requires an
    approved sealed proof; environment applicability stays external. No image creation, DB restore,
    implicit return, retry, final receipt or next baseline is supplied here.
    """
    import hashlib
    import json
    import re
    from pathlib import Path, PurePosixPath
    from types import SimpleNamespace
    from urllib.parse import unquote, urlsplit
    root, markers, wanted_markers = Path(root), {}, {}
    result = dict(status='OPERATION_HOLD_REQUIRES_OBSERVATION', releaseReady=False,
                  operationStatus='UNKNOWN', markers=markers)
    config_files = {
        'config/__init__.py': 'a79e374991bf7d0525594ebdde0691ee21502027a15bb3e8443835be45ef860a',
        'config/settings.py': '5712caeda80cc397bfd995141f29cc5c248835718c0dc0075796fc0c43b167a4'}
    forward = ('stop-intent.json', 'stop-confirmed.json', 'start-intent.json', 'start-confirmed.json')
    returning = tuple('return-' + name for name in forward)

    def unique(pairs):
        value = {}
        for key, entry in pairs:
            require(key not in value, 'SOURCE_JSON_DUPLICATE_KEY')
            value[key] = entry
        return value

    def parse(value):
        try:
            return json.loads(value, object_pairs_hook=unique)
        except (ValueError, UnicodeError):
            raise RuntimeError('SOURCE_JSON_INVALID') from None

    def raw(path, maximum):
        require(not any(p.is_symlink() for p in (path, *path.parents)), 'SOURCE_PACKAGE_PATH')
        require(path.is_file() and path.stat().st_size <= maximum, 'SOURCE_FILE_LIMIT')
        with path.open('rb') as stream:
            value = stream.read(maximum + 1)
        require(len(value) <= maximum, 'SOURCE_FILE_LIMIT')
        return value

    def reserve(path):
        require(not path.exists() and not path.is_symlink(), 'EXISTING_ATTEMPT_OBSERVE_NO_RETRY')
        path.mkdir(mode=0o700)
        core.private_probe_root(path)

    def summarize():
        require(not (root/'apply').is_symlink(), 'SOURCE_PACKAGE_PATH')
        for name in (*forward, *returning):
            path = root/'apply'/name
            row = dict(exists=path.exists() or path.is_symlink())
            if row['exists']:
                try:
                    value = raw(path, 4096)
                    record = parse(value)
                    row.update(sha256=hashlib.sha256(value).hexdigest(), jsonObject=isinstance(record, dict))
                    if name in wanted_markers:
                        row['valid'] = any(isinstance(record, dict) and record == expected
                            and all(type(record[key]) is type(v) for key, v in expected.items())
                            for expected in wanted_markers[name])
                except Exception:
                    row['unreadable'] = True
            markers[name] = row

    try:
        core.private_probe_root(root)
        summarize()
        with leaves.release_lease() as lease:
            core._pg_fence_lease(lease)
            require(mode in ('preflight', 'apply', 'observe', 'recover'), 'SOURCE_MODE')
            manifest_raw = raw(root/'manifest.json', 2*1024*1024)
            require(parse(manifest_raw) == manifest, 'SOURCE_MANIFEST_BINDING')
            files = manifest.get('files')
            require(isinstance(files, dict) and 1 <= len(files) <= 10000, 'SOURCE_MANIFEST_FILES')
            total = 0
            for name, expected in files.items():
                require(isinstance(name, str) and name not in ('', '.', 'manifest.json')
                        and str(PurePosixPath(name)) == name and not PurePosixPath(name).is_absolute()
                        and '..' not in PurePosixPath(name).parts and '\\' not in name and ':' not in name
                        and not any(ord(c) < 32 or ord(c) == 127 for c in name), 'SOURCE_PACKAGE_PATH')
                require(isinstance(expected, str) and re.fullmatch('[a-f0-9]{64}', expected), 'SOURCE_PACKAGE_HASH')
                value = raw(root/name, 8*1024*1024)
                total += len(value)
                require(total <= 64*1024*1024, 'SOURCE_PACKAGE_LIMIT')
                require(hashlib.sha256(value).hexdigest() == expected, 'SOURCE_PACKAGE_HASH')

            def sealed(name, maximum=2*1024*1024):
                require(isinstance(name, str) and name in files, 'SOURCE_UNSEALED_INPUT')
                value = raw(root/name, maximum)
                require(hashlib.sha256(value).hexdigest() == files[name], 'SOURCE_PACKAGE_HASH')
                return value

            require(parse(sealed('profile.json')) == profile, 'SOURCE_PROFILE_BINDING')
            require(profile.get('route') == 'SAME_SCHEMA_0204', 'UNKNOWN_RELEASE_ROUTE')
            p = profile['sameSchema']
            required_fields = {
                'format', 'seal', 'before', 'staged', 'postgres', 'artifacts', 'databaseURLSHA256',
                'compatibilityProof', 'admittedModes', 'oomLifecycleVerified'}
            require(isinstance(p, dict), 'SOURCE_PROFILE_FIELDS')
            proof_fields = {'oomLifecycleProof'} if p.get('oomLifecycleVerified') is True else set()
            require(set(p) == required_fields | proof_fields
                    and p['format'] == 'ERP_READY_SAME_SCHEMA_0204_V1', 'SOURCE_PROFILE_FIELDS')
            require(isinstance(p['admittedModes'], list) and mode in p['admittedModes']
                    and len(set(p['admittedModes'])) == len(p['admittedModes'])
                    and set(p['admittedModes']) <= {'preflight', 'apply', 'observe', 'recover'},
                    'SOURCE_MODE_NOT_ADMITTED')
            require(type(p['oomLifecycleVerified']) is bool, 'OOM_PROOF_REQUIRED')
            oom = False
            if p['oomLifecycleVerified'] is True:
                proof_path = p['oomLifecycleProof']
                proof_raw = sealed(proof_path, 4096)
                oom = verified_oom_lifecycle(proof_raw, files[proof_path])
            before, staged, pg = (parse(sealed(p[key])) for key in ('before', 'staged', 'postgres'))
            old_id, new_id, pg_id = before['Id'], staged['Id'], pg['Id']
            require(all(isinstance(cid, str) and re.fullmatch('[a-f0-9]{64}', cid)
                        for cid in (old_id, new_id, pg_id)) and len({old_id, new_id, pg_id}) == 3
                    and old_id == profile['oldContainer'] and before['Name'] == '/'+profile['oldName']
                    and pg_id == profile['postgresContainer'], 'SOURCE_SNAPSHOT_BINDING')
            wanted_markers.update({
                'stop-intent.json': [dict(id=old_id, status='ATTEMPTED_UNKNOWN')],
                'stop-confirmed.json': [dict(id=old_id, stopped=True)],
                'start-intent.json': [dict(id=new_id, status='ATTEMPTED_UNKNOWN')],
                'start-confirmed.json': [dict(id=new_id, running=True)],
                'return-stop-intent.json': [dict(id=new_id, status='ATTEMPTED_UNKNOWN', action='STOP'),
                                            dict(id=new_id, status='OBSERVED_INACTIVE', action='OBSERVE_INACTIVE')],
                'return-stop-confirmed.json': [dict(id=new_id, stopped=True, method=method)
                                               for method in ('POST', 'OBSERVED_NO_RESTART')],
                'return-start-intent.json': [dict(id=old_id, status='ATTEMPTED_UNKNOWN')],
                'return-start-confirmed.json': [dict(id=old_id, running=True)]})
            summarize()
            seal, artifacts = p['seal'], {}
            require(isinstance(p['artifacts'], dict)
                    and set(p['artifacts']) == {seal['oldImage'], seal['newImage']}, 'SOURCE_IMAGE_ARTIFACTS')
            for prefix in ('old', 'new'):
                image = seal[prefix+'Image']
                paths = p['artifacts'][image]
                require(isinstance(paths, dict) and set(paths) == {'manifest', 'receipt'}, 'SOURCE_IMAGE_ARTIFACTS')
                source_raw = sealed(paths['manifest'])
                source_files = parse(source_raw).get('files', {})
                require(isinstance(source_files, dict) and '.env' not in source_files
                        and all(source_files.get(name) == sha for name, sha in config_files.items()),
                        'SOURCE_SETTINGS_CHANGED')
                artifacts[image] = dict(manifestBytes=source_raw, manifestSHA256=files[paths['manifest']],
                    receiptBytes=sealed(paths['receipt'], 16384), receiptSHA256=files[paths['receipt']],
                    sourceSHA256=seal[prefix+'SourceSHA256'], checkpoint=seal[prefix+'Checkpoint'])
            cached = cached_image_schema_runner(runner, artifacts)
            compatibility = parse(sealed(p['compatibilityProof'], 16384))
            require(isinstance(compatibility, dict) and compatibility.get('state') == 'PASS_SOURCE_CONDITIONAL'
                    and compatibility.get('oldSourceSHA256') == seal['oldSourceSHA256']
                    and compatibility.get('newSourceSHA256') == seal['newSourceSHA256']
                    and compatibility.get('conditions') == ['AI_OFF', 'UNCHANGED_SEALED_CONFIGURATION'],
                    'SOURCE_COMPATIBILITY_BINDING')
            # Historical snapshots are never rewritten to imitate current state.
            verify_same_schema_stage(update, cached, before, staged, seal,
                                     oom_lifecycle_verified=oom)
            for row in (before, staged):
                policy = row['HostConfig'].get('RestartPolicy')
                require(policy == {'Name': 'no', 'MaximumRetryCount': 0}
                        and type(policy['MaximumRetryCount']) is int
                        and row['HostConfig']['AutoRemove'] is False, 'SOURCE_RETAINED_NO_RESTART')
            database = profile['database']
            binding = dict(appIDs=[old_id, new_id], pgID=pg_id,
                           database=database, appUser=before['Config']['User'])
            health, schema = same_schema_callbacks(binding)
            config = same_schema_configuration_probe(dict(appIDs=[old_id, new_id],
                appUser=binding['appUser'], databaseURLSHA256=p['databaseURLSHA256']))

            def pg_signature(row):
                state = row['State']
                require(row['Id'] == pg_id and state['Running'] is True and state['Status'] == 'running'
                        and type(state['Pid']) is int and state['Pid'] > 0 and state['Paused'] is False
                        and state['Restarting'] is False and state['OOMKilled'] is False,
                        'POSTGRES_BINDING_DRIFT')
                return runner.digest({key: row[key] for key in (
                    'Id', 'Name', 'Image', 'Config', 'HostConfig', 'Mounts', 'NetworkSettings', 'RestartCount')} |
                    {'State': {key: state.get(key) for key in (
                        'Running', 'Status', 'Pid', 'StartedAt', 'FinishedAt', 'ExitCode', 'OOMKilled', 'Paused', 'Restarting')},
                     'Health': {key: value for key, value in state.get('Health', {}).items() if key != 'Log'}})

            expected_pg = pg_signature(pg)

            def env(row):
                pairs = row['Config']['Env']
                require(isinstance(pairs, list) and all(isinstance(v, str) and '=' in v for v in pairs),
                        'DATABASE_URL_BINDING')
                values = {}
                for pair in pairs:
                    key, value = pair.split('=', 1)
                    key = key.casefold()
                    require(key not in values, 'DATABASE_URL_BINDING')
                    values[key] = value
                return values

            def guard():
                core._pg_fence_lease(lease)
                current_pg = engine.inspect(pg_id)
                require(pg_signature(current_pg) == expected_pg, 'POSTGRES_BINDING_DRIFT')
                pg_env = env(current_pg)
                require(pg_env.get('postgres_db') == database and pg_env.get('postgres_user') == 'aios',
                        'DATABASE_URL_BINDING')
                for original in (before, staged):
                    cid = original['Id']
                    row = engine.inspect(cid)
                    require(row['Id'] == cid and row['Image'] == original['Image']
                            and row['Name'] == original['Name'] and row['Config'] == original['Config']
                            and row['Mounts'] == original['Mounts'], 'LIVE_CONFIGURATION_DRIFT')
                    state = row['State']
                    if cid == new_id and state['Status'] == 'created':
                        require(state['Running'] is False and type(state['Pid']) is int and state['Pid'] == 0
                                and isinstance(state['StartedAt'], str)
                                and state['StartedAt'].startswith('0001-01-01T00:00:00'),
                                'LIVE_CONFIGURATION_DRIFT')
                        update.verify_staged_projection(cached, before, row, oom_lifecycle_verified=oom)
                    else:
                        require(runner.projection(row) == runner.projection(before), 'LIVE_CONFIGURATION_DRIFT')
                    require(row['Config']['WorkingDir'] == '/app' and row['Config']['User'] == binding['appUser']
                            and all(m['Destination'] == '/app/data' for m in row['Mounts']),
                            'LIVE_CONFIGURATION_DRIFT')
                    values = env(row)
                    url = values.get('aios_database_url', '')
                    require(hashlib.sha256(url.encode()).hexdigest() == p['databaseURLSHA256']
                            and values.get('aios_ai_enabled', 'false').lower() in ('false', '0', 'off', 'no'),
                            'DATABASE_URL_BINDING')
                    parsed = urlsplit(url)
                    require(parsed.scheme in ('postgresql', 'postgresql+asyncpg', 'postgresql+psycopg')
                            and parsed.username == 'aios' and unquote(parsed.path) == '/'+database
                            and parsed.port in (None, 5432) and not parsed.query and not parsed.fragment,
                            'DATABASE_URL_BINDING')
                    require(not row['HostConfig'].get('ExtraHosts') and not row['HostConfig'].get('Dns'),
                            'DATABASE_NETWORK_BINDING')
                    pg_networks = current_pg['NetworkSettings']['Networks']
                    require(any(name in pg_networks and network.get('NetworkID')
                                and network['NetworkID'] == pg_networks[name].get('NetworkID')
                                and parsed.hostname in [*(pg_networks[name].get('Aliases') or []),
                                                        pg_networks[name].get('IPAddress')]
                                for name, network in row['NetworkSettings']['Networks'].items()),
                            'DATABASE_NETWORK_BINDING')
                    changes = engine.request('GET', '/containers/'+cid+'/changes')
                    require(isinstance(changes, list) and len(changes) <= 10000, 'WRITABLE_CONFIGURATION_CHANGED')
                    for change in changes:
                        path, kind = change['Path'], change['Kind']
                        require(isinstance(path, str) and type(kind) is int and kind in (0, 1, 2),
                                'WRITABLE_CONFIGURATION_CHANGED')
                        protected = path == '/app/.env' or path in ('/app/config/__init__.py', '/app/config/settings.py')
                        ancestor = path in ('/app', '/app/config') and kind != 0
                        require(not protected and not ancestor, 'WRITABLE_CONFIGURATION_CHANGED')
                core._pg_fence_lease(lease)

            def request(method, route, *args, **kwargs):
                require(method == 'POST' and route in {
                    '/containers/'+cid+suffix for cid in (old_id, new_id)
                    for suffix in ('/stop?t=10', '/start')}, 'UNSCOPED_ENGINE_EFFECT')
                guard()
                return engine.request(method, route, *args, **kwargs)

            checked = SimpleNamespace(inspect=engine.inspect, request=request)
            manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
            accepted = dict(status='SAME_SCHEMA_PREFLIGHT_PASS', manifestSHA256=manifest_sha, releaseReady=False)
            apply_root = root/'apply'
            if mode == 'observe':
                guard()
                actual = [engine.inspect(cid) for cid in (old_id, new_id)]
                heads = schema(old_id)
                status = 'UNKNOWN'
                pending = apply_root/('returned.json' if any(markers[n]['exists'] for n in returning) else 'pending.json')
                needed = (*forward, *returning) if pending.name == 'returned.json' else forward
                if pending.is_file() and all(markers[n].get('valid') is True for n in needed):
                    receipt = parse(raw(pending, 4096))
                    expected_status = 'RETURNED_UI_PENDING' if pending.name == 'returned.json' else 'BACKEND_SWITCHED_UI_PENDING'
                    if receipt == dict(status=expected_status, manifestSHA256=manifest_sha, releaseReady=False):
                        status = expected_status
                for names in (forward, returning):
                    for intent, confirmed in zip(names[::2], names[1::2]):
                        if markers[intent]['exists'] != markers[confirmed]['exists']:
                            status = 'UNKNOWN'
                if (root/'recover').exists() and status != 'RETURNED_UI_PENDING':
                    status = 'UNKNOWN'
                result.update(status='OBSERVED_ONLY', operationStatus=status,
                    attempt='apply' if apply_root.exists() else 'preflight' if (root/'preflight').exists() else 'none',
                    runningIDs=[row['Id'] for row in actual if row['State']['Running'] is True],
                    observedState={row['Id']: row['State']['Status'] for row in actual}, schemaHeads=heads)
                return result
            if mode == 'preflight':
                reserve(root/'preflight')
                guard()
                require(config(old_id) is True, 'CONFIGURATION_PROBE_FAILED')
                current, candidate = engine.inspect(old_id), engine.inspect(new_id)
                require(current['State']['StartedAt'] == before['State']['StartedAt'], 'LIVE_START_IDENTITY_DRIFT')
                verify_same_schema_stage(update, cached, current, candidate, seal,
                                         oom_lifecycle_verified=oom)
                require(schema(old_id) == ['0204'], 'LIVE_SAME_SCHEMA_NOT_OBSERVED')
                guard()
                update.exclusive(root/'preflight.json', accepted)
                result.update(accepted, operationStatus='PREFLIGHT_ONLY')
                return result
            require(parse(raw(root/'preflight.json', 4096)) == accepted, 'PREFLIGHT_NOT_ACCEPTED')
            if mode == 'apply':
                reserve(apply_root)
                guard()
                require(config(old_id) is True, 'CONFIGURATION_PROBE_FAILED')
                active = switch_same_schema(update, checked, cached, apply_root, before, staged,
                                            seal, health=health, schema=schema, oom_lifecycle_verified=oom)
                require(config(active['Id']) is True, 'CONFIGURATION_PROBE_FAILED')
                guard()
                receipt = dict(status='BACKEND_SWITCHED_UI_PENDING', manifestSHA256=manifest_sha, releaseReady=False)
                update.exclusive(apply_root/'pending.json', receipt)
            else:
                require(apply_root.is_dir() and not apply_root.is_symlink(), 'NO_EXISTING_ATTEMPT')
                require(not any(markers[n]['exists'] for n in returning), 'ALREADY_RETURNING_READ_STATUS')
                reserve(root/'recover')
                guard()
                active = return_same_schema(update, checked, cached, apply_root, before, staged,
                    engine.inspect(new_id), seal, health=health, schema=schema, oom_lifecycle_verified=oom)
                require(config(active['Id']) is True, 'CONFIGURATION_PROBE_FAILED')
                guard()
                receipt = dict(status='RETURNED_UI_PENDING', manifestSHA256=manifest_sha, releaseReady=False)
                update.exclusive(apply_root/'returned.json', receipt)
            summarize()
            result.update(receipt, operationStatus=receipt['status'])
            return result
    except Exception as error:
        try:
            summarize()
        except Exception:
            pass
        message = str(error)
        result.update(errorType=type(error).__name__,
                      safeCode=message if re.fullmatch('[A-Z0-9_]+', message) else None)
        return result



def verified_oom_lifecycle(raw, expected_sha256):
    """Validate an externally approved, sealed native proof without any I/O.

    Expected pins must come from the separately approved release manifest.
    A matching body/hash alone does not establish current daemon applicability
    or authorize OOM relaxation/deployment. The caller must retain provenance
    and obtain native admission separately. Only the existing created-phase
    projection exception may consume the resulting frozen boolean.
    """
    import hashlib
    import json
    import re
    require(type(raw) is bytes and len(raw) <= 4096
            and type(expected_sha256) is str and re.fullmatch('[a-f0-9]{64}', expected_sha256),
            'OOM_PROOF_INPUT')
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'OOM_PROOF_HASH')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'OOM_PROOF_DUPLICATE_KEY')
            result[key] = value
        return result

    try:
        proof = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise RuntimeError('OOM_PROOF_JSON') from None
    expected = dict(status='OWNED_OOM_LIFECYCLE_PROBE',
                    values=dict(created=False, running=None), removed=True, productionUnchanged=True)
    require(isinstance(proof, dict) and proof == expected
            and proof['values']['created'] is False and proof['values']['running'] is None
            and proof['removed'] is True and proof['productionUnchanged'] is True, 'OOM_PROOF_BODY')
    return True
