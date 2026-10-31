"""Image-only update for an attested fresh-install container, without Compose.

This extension deliberately leaves the installed Compose runner unchanged. Its
projection and image/schema probes are reused. A stopped reproduction with the
exact Engine create request must match before the live application can stop.
No database, environment, volume, network, frontend, or migration changes.
"""
from __future__ import annotations

import copy
import http.client
import json
import re
import socket
import time


class Hold(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise Hold(code)


def create_request(info, image, *, expected_networks):
    require(re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'IMMUTABLE_IMAGE')
    require(all(m['Destination'] == '/app/data' for m in info['Mounts']), 'SOURCE_MOUNT')
    require(not info['HostConfig']['AutoRemove'], 'ROLLBACK_MUST_BE_RETAINED')
    networks = info['NetworkSettings']['Networks']
    require(bool(expected_networks) and set(networks) == set(expected_networks), 'ATTESTED_NETWORKS_CHANGED')
    config = copy.deepcopy(info['Config'])
    config['Image'] = image
    config['HostConfig'] = copy.deepcopy(info['HostConfig'])
    # Engine-generated endpoint IDs, addresses and gateways are never replayed.
    config['NetworkingConfig'] = {'EndpointsConfig': {
        name: {k: copy.deepcopy(row[k]) for k in ('IPAMConfig', 'Links', 'Aliases', 'DriverOpts')
               if row.get(k) is not None}
        for name, row in networks.items()
    }}
    return config


def verify_staged_projection(runner, before, candidate, *, oom_lifecycle_verified=False):
    expected, observed = runner.projection(before), runner.projection(candidate)
    if observed != expected and oom_lifecycle_verified:
        # A native no-network canary must attest false at create -> null at start.
        # The running-container projection remains byte-exact below in switch().
        require(expected['host'].get('OomKillDisable') is None
                and observed['host'].get('OomKillDisable') is False, 'OOM_LIFECYCLE_MISMATCH')
        observed = copy.deepcopy(observed)
        observed['host']['OomKillDisable'] = None
    require(observed == expected, 'CONFIGURATION_REPRODUCTION_FAILED')


def verify_image_only(runner, before, candidate, base_image, new_image, schema, *, oom_lifecycle_verified=False):
    require(before['State']['Running'], 'BASE_NOT_RUNNING')
    require(before['Image'] == base_image, 'BASE_IMAGE_DRIFT')
    require(candidate['Image'] == new_image and not candidate['State']['Running'], 'CANDIDATE_NOT_STAGED')
    verify_staged_projection(runner, before, candidate, oom_lifecycle_verified=oom_lifecycle_verified)
    require(runner.inspect(base_image)['Config'] == runner.inspect(new_image)['Config'], 'IMAGE_CONFIGURATION_CHANGED')
    a, b = runner.image_schema(base_image), runner.image_schema(new_image)
    require(a == b and a['heads'] == schema, 'MIGRATION_OR_ENTRYPOINT_CHANGED')


class Engine:
    """The same bounded Unix HTTP pattern used by fresh_install.Native._engine."""
    def request(self, method, route, payload=None, *, absent=False):
        connection = http.client.HTTPConnection('localhost', timeout=10)
        try:
            connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.sock.settimeout(10)
            connection.sock.connect('/var/run/docker.sock')
            body = None if payload is None else json.dumps(payload).encode()
            require(body is None or len(body) <= 1048576, 'ENGINE_INPUT_LIMIT')
            connection.request(method, '/v1.44' + route, body, {'Content-Type': 'application/json'})
            response = connection.getresponse()
            raw = response.read(1048577)
            require(len(raw) <= 1048576, 'ENGINE_OUTPUT_LIMIT')
            if absent and response.status == 404:
                return None
            if response.status not in (200, 201, 204):
                # Preserve the native diagnostic on the server; callers may save
                # it privately, but receipts disclose only status and hash.
                self.last_error = {'status': response.status, 'body': raw.decode(errors='replace')}
                raise Hold('ENGINE_RESPONSE_'+str(response.status))
            return json.loads(raw) if raw else {}
        finally:
            connection.close()

    def inspect(self, cid):
        require(re.fullmatch('[a-f0-9]{64}', cid), 'EXACT_CONTAINER_ID')
        return self.request('GET', '/containers/' + cid + '/json')


def exclusive(path, value):
    import os
    with path.open('x', encoding='utf8') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def switch(engine, runner, root, before, staged, *, health, schema, oom_lifecycle_verified=False):
    """Caller owns the existing global release lease. Retain both containers.

    Every consequential effect has an exclusive intent and observation. Lost
    stop/start replies stay UNKNOWN; there is no implicit retry or cleanup.
    A confirmed failed candidate can be explicitly returned to the retained base.
    """
    require(not (root/'stop-intent.json').exists(), 'ALREADY_STARTED_READ_STATUS')
    current = engine.inspect(before['Id'])
    require(current['State']['Running'] and current['State']['StartedAt'] == before['State']['StartedAt']
            and runner.projection(current) == runner.projection(before), 'LIVE_CONFIGURATION_DRIFT')
    candidate = engine.inspect(staged['Id'])
    require(candidate['Image'] == staged['Image'] and not candidate['State']['Running'], 'STAGED_DRIFT')
    verify_staged_projection(runner, before, candidate, oom_lifecycle_verified=oom_lifecycle_verified)
    exclusive(root/'stop-intent.json', {'id': before['Id'], 'status': 'ATTEMPTED_UNKNOWN'})
    engine.request('POST', '/containers/'+before['Id']+'/stop?t=10')
    require(not engine.inspect(before['Id'])['State']['Running'], 'BASE_STOP_UNKNOWN')
    exclusive(root/'stop-confirmed.json', {'id': before['Id'], 'stopped': True})
    exclusive(root/'start-intent.json', {'id': candidate['Id'], 'status': 'ATTEMPTED_UNKNOWN'})
    engine.request('POST', '/containers/'+candidate['Id']+'/start')
    active = engine.inspect(candidate['Id'])
    require(active['State']['Running'], 'CANDIDATE_START_UNKNOWN')
    exclusive(root/'start-confirmed.json', {'id': candidate['Id'], 'running': True})
    deadline = time.monotonic()+60
    while time.monotonic() < deadline:
        active = engine.inspect(candidate['Id'])
        require(runner.projection(active) == runner.projection(before), 'POST_CONFIGURATION_DRIFT')
        if active['State']['Running'] and health():
            require(schema(candidate['Id']) == ['0194'], 'POST_SCHEMA_CHANGED')
            return active
        time.sleep(.5)
    raise Hold('HEALTH_TIMEOUT_EXPLICIT_RETURN_REQUIRED')
