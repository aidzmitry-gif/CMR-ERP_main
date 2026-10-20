"""Guarded private launcher; never import the application during preparation."""
import hashlib
import json
import os
from pathlib import Path


def main():
    profile = Path(os.environ['ERP_POOL_PROFILE']).resolve()
    value = json.loads(profile.read_text(encoding='utf-8'))
    assert value['kind'] == 'ERP_READY_PRIVATE_POOL3_V1'
    root = Path(os.environ['ERP_POOL_SOURCE_ROOT']).resolve()
    assert root.name == value['sourceRootName']
    for name, expected in value['sourceSHA256'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
    original = root / 'frontend/e2e/backend.py'
    fragment = profile.parent / 'G12KZ-observer-fragment.py'
    assert hashlib.sha256(fragment.read_bytes()).hexdigest() == value['fragmentSHA256']
    source = original.read_text(encoding='utf-8')
    anchor = 'db = app.state.core.services.db\n'
    assert source.count(anchor) == 1
    source = source.replace(anchor, anchor + '\n' + fragment.read_text(encoding='utf-8') + '\n', 1)
    marker = "'background_workers': False, 'email_enabled': False, 'egress_guard': True}"
    assert source.count(marker) == 1
    source = source.replace(marker, marker[:-1] + ", 'pool_diag': _diag_snapshot()}", 1)
    # Original filename keeps path resolution and the existing guarded seed/egress/lifespan.
    exec(compile(source, str(original), 'exec'), {'__name__': '__main__', '__file__': str(original)})


if __name__ == '__main__':
    main()
