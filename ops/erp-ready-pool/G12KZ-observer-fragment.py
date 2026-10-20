"""Private synthetic-runtime observation only. Insert after existing E2E db binding."""
import contextvars
import importlib.metadata
from collections import Counter
from threading import Lock

from sqlalchemy import event

_diag_stage = contextvars.ContextVar('pool_diag_stage', default=0)
_diag_active = {}
_diag_lock = Lock()
_diag_totals = {'out': 0, 'in': 0, 'anomalies': 0}
_diag_paths = {'/sales/calls/stream': 3, '/__e2e_isolation': 2,
               '/system/access': 1, '/sales/clients/owners': 4}


class _PoolObservation:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = _diag_stage.set(_diag_paths.get(scope.get('path'), 0))
        try:
            await self.app(scope, receive, send)
        finally:
            _diag_stage.reset(token)


def _diag_checkout(_connection, record, _proxy):
    with _diag_lock:
        _diag_totals['out'] += 1
        if id(record) in _diag_active:
            _diag_totals['anomalies'] += 1
        _diag_active[id(record)] = _diag_stage.get()


def _diag_checkin(_connection, record):
    with _diag_lock:
        _diag_totals['in'] += 1
        if _diag_active.pop(id(record), None) is None:
            _diag_totals['anomalies'] += 1


def _diag_snapshot():
    from modules.sales import calls

    pool = db.engine.sync_engine.pool
    size_method = getattr(pool, 'size', None)
    size = size_method() if callable(size_method) else -1
    overflow = getattr(pool, '_max_overflow', -1)
    with _diag_lock:
        active = tuple(_diag_active.values())
        totals = dict(_diag_totals)
    owners = Counter(active)
    return {
        'schema': 1,
        'sqlalchemy': importlib.metadata.version('sqlalchemy'),
        'aiosqlite': importlib.metadata.version('aiosqlite'),
        'poolClass': {'AsyncAdaptedQueuePool': 1, 'StaticPool': 2, 'NullPool': 3}.get(type(pool).__name__, 0),
        'size': size if type(size) is int else -1,
        'maxOverflow': overflow if type(overflow) is int else -1,
        'active': len(active),
        'out': totals['out'], 'in': totals['in'],
        'anomalies': totals['anomalies'],
        'owners': [[stage, owners.get(stage, 0)] for stage in range(5)],
        'subscribers': [len(calls._subscribers.get(owner, ())) for owner in (2901, 2902)],
    }


# Listen on the existing engine; do not change limits, sessions or dependencies.
db.init_engine()
event.listen(db.engine.sync_engine, 'checkout', _diag_checkout)
event.listen(db.engine.sync_engine, 'checkin', _diag_checkin)
app.add_middleware(_PoolObservation)
