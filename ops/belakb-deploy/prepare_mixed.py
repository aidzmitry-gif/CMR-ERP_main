#!/usr/bin/env python3
"""Export committed backend sources and verify an offline immutable image; no apply."""
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import uuid
from pathlib import Path, PurePosixPath

CHAIN = 'CRM-REL-001'
OPT_IN = CHAIN + '-isolated-only'
APPLICATION_CHECKPOINT = 'af9ba9f879b083758e31bc9296316afc13b92b60'
RUNTIME = 'sha256:469fbba3826e14647fb9b03280843ff591fc6f875244bb17e08f51043ef21319'
RUNTIME_ALIAS = 'crm-rel-001-g06-runtime:469fbba3826e'
HEAD = 'crm_rel_001_native_catalog_01'
PINS = {
    'finance': '59832b2f14a2ee02d8db266a67f8206616bdcd94',
    'hr': 'f8a6e0142f1920b07ec56818f42d156a602ff9c3',
    'leads': '9a304f771ba74369ded199168e0e1da3ad6348d2',
    'logistics': '6923d2e021980ef2546f382364d38dc34a0fef29',
    'marketing': 'd4ed67fdc9b41e7abc370112e1a3fa8a3fe1e282',
    'procurement': '0f60bb3173c42ad080301d68586b70abde1ab5ac',
    'production': 'be7d7e198bf09cc41c642d22125db401da5adc48',
    'sales': '8ff96be028282f6e4cf244d14e58cbf8299b54af',
    'service': '3d33800c44865cd7a7373b29192c5d59d3c4bec8',
    'wms': '59de6378f91b803e849c5966b4c606df2b190e9a',
}
PREFIXES = ('config/', 'connectors/', 'core/', 'integrations/', 'modules/',
            'migrations/', 'docker/', 'scripts/')
ROOT_FILES = {'main.py', 'alembic.ini', 'requirements.txt', 'pyproject.toml', 'Dockerfile'}
CLOSURE_FILES = {'ops/sales_mail/__init__.py', 'ops/sales_mail/config.py',
                 'ops/sales_mail/queue.py', 'ops/sales_mail/relay.py'}
PROOFS = {'tests/integration/crm_rel_001_migration_proof.py',
          'tests/integration/crm_rel_001_financial_proof.py'}


class Blocked(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise Blocked(code)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def file_sha(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for body in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(body)
    return result.hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def run(args, *, data=None, timeout=180):
    try:
        result = subprocess.run(args, input=data, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise Blocked('COMMAND_UNAVAILABLE_OR_TIMEOUT') from None
    require(result.returncode == 0, 'COMMAND_FAILED_OUTPUT_REDACTED')
    return result.stdout


def inspect(name):
    return json.loads(run(['docker', 'inspect', name]))[0]


def projection(info):
    config = dict(info['Config'])
    config.pop('Hostname', None)
    config.pop('Image', None)
    config['Labels'] = {k: v for k, v in (config.get('Labels') or {}).items()
                        if not k.startswith('com.docker.compose.')}
    config['Env'] = sorted(config.get('Env') or [])
    return {'config': config, 'host': info['HostConfig'], 'mounts': info['Mounts'],
            'networks': sorted(info['NetworkSettings']['Networks'])}


def protected_new_directory(path):
    require(path.is_absolute(), 'ABSOLUTE_OUTPUT_REQUIRED')
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'OUTPUT_SYMLINK')
    require(not path.exists(), 'OUTPUT_EXISTS_NO_RETRY')
    # Windows Python 3.12's special 0700 ACL is incompatible with restricted tokens.
    # Windows exports contain committed code only; server dumps still require POSIX 0700.
    path.mkdir(mode=0o755 if os.name == 'nt' else 0o700, parents=False)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf8')
    path.chmod(0o600)


def selected(name):
    p = PurePosixPath(name)
    require(not p.is_absolute() and '..' not in p.parts and '\\' not in name, 'SOURCE_PATH')
    if not (name in ROOT_FILES | PROOFS | CLOSURE_FILES or name.startswith(PREFIXES)):
        return False
    forbidden = {'__pycache__', 'node_modules', '.next', '.git', 'uploads', 'backups',
                 'data', '.pytest_cache', '.ruff_cache'}
    require(not forbidden.intersection(p.parts), 'GENERATED_OR_DATA_SOURCE')
    require(not any(part.startswith('.env') for part in p.parts), 'SECRET_SOURCE_PATH')
    require(p.suffix.lower() not in {'.pem', '.key', '.p12', '.db', '.sqlite', '.pyc',
                                    '.csv', '.xlsx', '.docx', '.log'}, 'PRIVATE_OR_GENERATED_SOURCE')
    return True


def tree(repo, checkpoint, *, module=False):
    require(re.fullmatch('[a-f0-9]{40}', checkpoint), 'EXACT_CHECKPOINT_REQUIRED')
    output = run(['git', '-C', str(repo), 'ls-tree', '-r', '-z', checkpoint])
    files, pins = {}, {}
    for record in output.split(b'\0'):
        if not record:
            continue
        metadata, path = record.split(b'\t', 1)
        mode, kind, object_id = metadata.decode().split()
        name = path.decode('utf8')
        # Environment examples are committed in connectors; no env blob is read/exported.
        if any(part.startswith('.env') for part in PurePosixPath(name).parts):
            continue
        if kind == 'commit':
            require(not module, 'NESTED_GITLINK_UNSUPPORTED')
            pins[name.removeprefix('modules/')] = object_id
        elif module:
            # Module code/assets only; never export its private docs or datasets.
            if name.endswith(('.py', '.html', '.jinja', '.j2', '.json', '.xsd', '.xml',
                              '.css', '.js', '.txt', '.toml', '.sql')):
                require(selected('modules/pinned/' + name), 'MODULE_SOURCE_PATH')
                require(mode in ('100644', '100755'), 'SOURCE_SYMLINK_OR_MODE')
                files[name] = (mode, object_id)
        elif selected(name):
            require(mode in ('100644', '100755'), 'SOURCE_SYMLINK_OR_MODE')
            files[name] = (mode, object_id)
    return files, pins


def prepare(repo, package_checkpoint, output):
    original, pins = tree(repo, APPLICATION_CHECKPOINT)
    current, current_pins = tree(repo, package_checkpoint)
    require(pins == current_pins == PINS, 'PINNED_MODULES_CHANGED')
    require(current == original, 'APPLICATION_CHANGED_AFTER_ACCEPTANCE')
    exports = {name: (repo, *spec) for name, spec in current.items()}
    for name, checkpoint in PINS.items():
        module_repo = repo / 'modules' / name
        module_files, _ = tree(module_repo, checkpoint, module=True)
        require(module_files, 'PINNED_MODULE_EXPORT_EMPTY')
        exports.update({f'modules/{name}/{p}': (module_repo, *spec)
                        for p, spec in module_files.items()})
    require(ROOT_FILES | PROOFS | CLOSURE_FILES <= exports.keys(), 'FULL_APPLICATION_ROOT_MISSING')
    require('docker/app-entrypoint.sh' in exports and 'core/runtime/app.py' in exports,
            'APPLICATION_ENTRYPOINT_MISSING')
    require(all(any(p.startswith(f'modules/{n}/') for p in exports) for n in PINS),
            'MODULE_CLOSURE_MISSING')
    require(not output.resolve().is_relative_to(repo.resolve()), 'OUTPUT_INSIDE_REPOSITORY')
    protected_new_directory(output)
    context = output / 'context'
    source = context / 'source'
    source.mkdir(mode=0o755 if os.name == 'nt' else 0o700, parents=True)
    files, blobs = {}, {}
    for name, (repository, mode, object_id) in sorted(exports.items()):
        body = run(['git', '-C', str(repository), 'cat-file', 'blob', object_id])
        require(len(body) <= 16 * 1024 * 1024, 'SOURCE_FILE_TOO_LARGE')
        target = source / name
        target.parent.mkdir(mode=0o755 if os.name == 'nt' else 0o700, parents=True, exist_ok=True)
        target.write_bytes(body)
        target.chmod(0o700 if mode == '100755' else 0o600)
        files[name], blobs[name] = sha(body), object_id
    manifest = {'format': 1, 'chain': CHAIN, 'application_checkpoint': APPLICATION_CHECKPOINT,
                'package_checkpoint': package_checkpoint, 'gitlinks': PINS, 'files': files,
                'git_blobs': blobs, 'runtime_image': RUNTIME, 'head': HEAD,
                'frontend': {'status': 'PENDING_PRODUCTION_OIDC_PACKAGE'},
                'status': 'SOURCE_PREPARED_NOT_RELEASE_READY'}
    write_json(output / 'manifest.json', manifest)
    labels = (f'LABEL crm-rel-001-source={digest(files)} '
              f'crm-rel-001-package={package_checkpoint}\n')
    (context / 'Dockerfile').write_text(
        f'FROM {RUNTIME_ALIAS}\nWORKDIR /app\nRUN rm -rf /app && mkdir /app\n'
        'COPY source/ /app/\nRUN chmod +x /app/docker/app-entrypoint.sh\n' + labels +
        'EXPOSE 8000\nENTRYPOINT ["docker/app-entrypoint.sh"]\n', encoding='utf8')
    return manifest


def known_absent(found):
    # Match the complete Docker error, never a substring in a mixed/permission failure.
    return (found.returncode == 1 and found.stdout.strip() in (b'', b'[]') and
            re.fullmatch(rb'(?:error:[ \t]*|error response from daemon:[ \t]*)?no such '
                         rb'(?:object|container|image)(?::[ \t]*[a-z0-9][a-z0-9_.:/-]*)?',
                         found.stderr.strip(), re.IGNORECASE) is not None)


def private_probe_root(path):
    require(path.is_absolute() and path.is_dir() and
            not any(p.is_symlink() for p in (path, *path.parents)), 'PRIVATE_PROBE_ROOT')
    if os.name != 'nt':
        info = path.stat()
        require(stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.geteuid(),
                'PRIVATE_PROBE_ROOT_PERMISSIONS')


def write_probe_state(path, record):
    pending = path.with_suffix('.pending')
    # Atomic replacement leaves a usable pre-create record after interrupted updates.
    require(not pending.is_symlink(), 'PROBE_PENDING_SYMLINK')
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC |
                 getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='utf8') as handle:
        json.dump(record, handle, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(pending, path)
    if os.name != 'nt':
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def remove_probe(name, image, network, *, container_id=None):
    found = subprocess.run(['docker', 'inspect', name], capture_output=True, timeout=30)
    if found.returncode:
        require(known_absent(found), 'PROBE_STATE_UNKNOWN')
        return
    info = json.loads(found.stdout)[0]
    require(info['Name'] == '/' + name and info['Image'] == image and
            info['Config']['Labels'].get('crm-rel-001-owner') == name, 'PROBE_OWNER')
    require(re.fullmatch('[a-f0-9]{64}', info['Id']) and
            (container_id is None or info['Id'] == container_id), 'PROBE_IDENTITY')
    host = info['HostConfig']
    require(host['NetworkMode'] == network and host['ReadonlyRootfs'] and
            not host['Privileged'] and not host['Binds'] and not host['PortBindings'],
            'PROBE_BOUNDARY')
    require(all(m['Type'] == 'tmpfs' and m['Destination'] == '/tmp'
                for m in info['Mounts']), 'PROBE_MOUNTS')
    run(['docker', 'rm', '-f', '-v', info['Id']])
    found = subprocess.run(['docker', 'inspect', name], capture_output=True, timeout=30)
    require(known_absent(found), 'PROBE_CLEANUP_UNCONFIRMED')
    return info['Id']


def recover_probe(path):
    private_probe_root(path.parent)
    require(path.is_file() and not path.is_symlink(), 'PROBE_STATE_FILE')
    record = json.loads(path.read_bytes())
    name = record['name']
    require(record['format'] == 1 and record['chain'] == CHAIN and
            re.fullmatch('crm-rel-001-g06-probe-[a-f0-9]{32}', name) and
            record['owner'] == name and path.name == name + '.json' and
            record['state_root'] == str(path.parent), 'PROBE_RECORD_IDENTITY')
    require(re.fullmatch('sha256:[a-f0-9]{64}', record['image']) and
            (record['network'] == 'none' or
             re.fullmatch('container:[a-f0-9]{64}', record['network'])), 'PROBE_RECORD_BOUNDARY')
    cidfile = path.parent / (name + '.cid')
    require(record['cidfile'] == str(cidfile) and not cidfile.is_symlink(), 'PROBE_CIDFILE')
    container_id = record.get('container_id')
    if cidfile.exists():
        require(cidfile.is_file(), 'PROBE_CIDFILE')
        observed = cidfile.read_text().strip()
        # Docker may create an empty cidfile before a process is interrupted.
        # Only that unassigned state can fall back to strict name/owner adoption.
        require(not observed or (re.fullmatch('[a-f0-9]{64}', observed) and
                (container_id is None or container_id == observed)), 'PROBE_CID_MISMATCH')
        container_id = observed or container_id
    require(container_id is None or re.fullmatch('[a-f0-9]{64}', container_id), 'PROBE_CID_FORMAT')
    record['container_id'] = container_id
    write_probe_state(path, record)
    observed = remove_probe(name, record['image'], record['network'], container_id=container_id)
    record.update(container_id=observed or container_id, status='OWNED_PROBE_REMOVED_OR_ABSENT')
    write_probe_state(path, record)
    return record


def probe(image, program, payload=None, *, state_root, pg_id=None):
    require(re.fullmatch('sha256:[a-f0-9]{64}', image), 'IMMUTABLE_IMAGE_REQUIRED')
    require(pg_id is None or re.fullmatch('[a-f0-9]{64}', pg_id), 'OWNED_PG_ID_REQUIRED')
    private_probe_root(state_root)
    name = 'crm-rel-001-g06-probe-' + uuid.uuid4().hex
    network = 'none' if pg_id is None else 'container:' + pg_id
    path, cidfile = state_root / (name + '.json'), state_root / (name + '.cid')
    require(not path.exists() and not cidfile.exists() and not cidfile.is_symlink(),
            'PROBE_STATE_EXISTS_NO_RETRY')
    record = {'format': 1, 'chain': CHAIN, 'name': name, 'owner': name, 'image': image,
              'network': network, 'state_root': str(state_root), 'cidfile': str(cidfile),
              'container_id': None, 'status': 'PREPARED_BEFORE_DOCKER_CREATE'}
    write_probe_state(path, record)
    args = ['docker', 'run', '--rm', '-i', '--pull=never', '--name', name,
            '--cidfile', str(cidfile),
            '--label', 'crm-rel-001-owner=' + name, '--network=' + network,
            '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--memory=1g', '--cpus=1', '--pids-limit=128',
            '--tmpfs=/tmp:rw,noexec,nosuid,size=128m', '--workdir=/app',
            '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'AIOS_ENVIRONMENT=dev',
            '-e', 'AIOS_AUTH_MODE=dev', '-e', 'AIOS_SKIP_AUTOMIGRATE=1',
            '-e', 'AIOS_DATABASE_URL=' + ('sqlite+aiosqlite:///:memory:' if pg_id is None
                else 'postgresql+psycopg://aios@127.0.0.1:5432/aios_copy'),
            '--entrypoint=python', image, '-B', '-c', program]
    try:
        result = run(args, data=payload, timeout=240)
        require(cidfile.is_file() and not cidfile.is_symlink(), 'PROBE_CID_MISSING')
        container_id = cidfile.read_text().strip()
        require(re.fullmatch('[a-f0-9]{64}', container_id), 'PROBE_CID_FORMAT')
        record.update(container_id=container_id, status='PROBE_EXECUTED')
        write_probe_state(path, record)
        return result
    finally:
        try:
            recover_probe(path)
        except (Exception, KeyboardInterrupt):
            raise Blocked('PROBE_CLEANUP_UNCONFIRMED') from None


IMAGE_PROBE = '''import hashlib,json,sys,importlib,importlib.metadata as m
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.version import Version
manifest=json.load(sys.stdin); root=Path('/app')
actual={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
assert not any(p.is_symlink() for p in root.rglob('*')), 'IMAGE_SYMLINK'
assert actual==manifest['files'], 'IMAGE_SOURCE_MISMATCH'
for line in (root/'requirements.txt').read_text().splitlines():
 line=line.split('#',1)[0].strip()
 if not line: continue
 r=Requirement(line)
 if r.marker is None or r.marker.evaluate(): assert Version(m.version(r.name)) in r.specifier, 'DEPENDENCY_MISMATCH'
for name in ['main','pypdf','lxml.etree']: importlib.import_module(name)
from weasyprint import HTML
from pypdf import PdfReader
from io import BytesIO
pdf=HTML(string='<html><body>Проверка PDF 177 BYN</body></html>').write_pdf()
text=''.join(p.extract_text() or '' for p in PdfReader(BytesIO(pdf)).pages)
assert '177 BYN' in text and 'Проверка' in text, 'NATIVE_PDF_FAILED'
heads=ScriptDirectory.from_config(Config('/app/alembic.ini')).get_heads()
assert heads==[manifest['head']], 'IMAGE_HEAD_MISMATCH'
print(json.dumps({'status':'IMMUTABLE_BACKEND_IMAGE_VERIFIED','source_sha256':hashlib.sha256(json.dumps(actual,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'head':heads[0],'native_pdf_bytes':len(pdf)}))
'''


def verify_image(manifest, image, *, state_root):
    require(manifest['gitlinks'] == PINS and manifest['application_checkpoint'] ==
            APPLICATION_CHECKPOINT, 'PACKAGE_SOURCE_IDENTITY')
    require(image != RUNTIME, 'TEST_RUNTIME_IS_NOT_RELEASE_IMAGE')
    info = inspect(image)
    require(info['Id'] == image and info['Architecture'] == 'amd64', 'IMAGE_IDENTITY')
    config = info['Config']
    require(config['WorkingDir'] == '/app' and config['Entrypoint'] ==
            ['docker/app-entrypoint.sh'], 'IMAGE_ENTRYPOINT')
    require(config['Labels'].get('crm-rel-001-source') == digest(manifest['files']) and
            config['Labels'].get('crm-rel-001-package') == manifest['package_checkpoint'],
            'IMAGE_PROVENANCE')
    probe(image, 'import subprocess; subprocess.run(["python","-m","pip","check"],check=True)',
          state_root=state_root)
    result = json.loads(probe(image, IMAGE_PROBE, json.dumps(manifest).encode(), state_root=state_root))
    require(result['status'] == 'IMMUTABLE_BACKEND_IMAGE_VERIFIED' and
            result['source_sha256'] == digest(manifest['files']) and result['head'] == HEAD,
            'IMAGE_PROOF_IDENTITY')
    return dict(result, image=image, package_checkpoint=manifest['package_checkpoint'],
                probe_state_root=str(state_root), production_changes=0, release_ready=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-opt-in', required=True, choices=[OPT_IN])
    sub = parser.add_subparsers(dest='phase', required=True)
    p = sub.add_parser('source')
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--package-checkpoint', required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('verify-image')
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--manifest-sha256', required=True)
    p.add_argument('--image', required=True)
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--probe-state-root', type=Path, required=True)
    p = sub.add_parser('recover-probe')
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--state-sha256', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if args.phase == 'source':
        result = prepare(args.repo, args.package_checkpoint, args.output)
        print(json.dumps({'status': result['status'], 'manifest_sha256':
                          sha((args.output / 'manifest.json').read_bytes())}))
    elif args.phase == 'verify-image':
        require(sha(args.manifest.read_bytes()) == args.manifest_sha256, 'MANIFEST_CHANGED')
        require(not args.receipt.exists() and not args.receipt.is_symlink(), 'RECEIPT_EXISTS')
        require(args.receipt.is_absolute() and args.receipt.parent == args.probe_state_root,
                'PROBE_STATE_RECEIPT_BINDING')
        result = verify_image(json.loads(args.manifest.read_bytes()), args.image,
                              state_root=args.probe_state_root)
        write_json(args.receipt, dict(result, manifest_sha256=args.manifest_sha256))
        print(json.dumps(result))
    else:
        require(sha(args.state.read_bytes()) == args.state_sha256, 'PROBE_STATE_CHANGED')
        result = recover_probe(args.state)
        print(json.dumps({'status': result['status'], 'state': str(args.state),
                          'state_sha256': sha(args.state.read_bytes()), 'production_changes': 0}))


if __name__ == '__main__':
    main()
