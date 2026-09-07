"""Mottor v1 delivery adapter. Deploy only after the v1 receiver is verified.

Legacy accepted/sending/uncertain rows are deliberately not replayed: their old
endpoint had no stable receipt. Their CRM lead IDs require separate reconciliation.
"""
import argparse
import json
import os
import sys
import urllib.parse
from pathlib import Path

import mottor_bridge as source
import receipt_queue as receipts

ENDPOINT = 'http://127.0.0.1:8000/integrations/intake/v1'


def stage(db):
    for sid, raw in db.execute("SELECT source_id,payload FROM deliveries WHERE state='pending'").fetchall():
        try:
            lead = source.intake_payload(json.loads(raw))
            key = 'mottor:1191119:' + str(sid)
            with db:
                receipts.enqueue(db, {'namespace': 'enersys.by', 'source_id': key,
                                      'delivery_id': key + ':initial', 'lead': lead})
                db.execute("UPDATE deliveries SET state='v1_pending' WHERE source_id=?", (sid,))
        except ValueError:
            with db:
                db.execute("UPDATE deliveries SET state='review',last_error='v1_envelope_invalid' WHERE source_id=?", (sid,))


def reconcile(db):
    # The immutable original source remains in the queue after confirmation.
    with db:
        db.execute('''UPDATE deliveries SET state='delivered',last_error=''
            WHERE state='v1_pending' AND EXISTS (
              SELECT 1 FROM receipt_outbox r WHERE r.namespace='enersys.by'
              AND r.delivery_id='mottor:1191119:' || deliveries.source_id || ':initial'
              AND r.state='delivered' AND r.lead_id>0)''')


def cycle(db, fetch, post, get, now):
    collection_error = None
    try:
        source.collect(db, fetch, now)
    except Exception as exc:
        collection_error = type(exc).__name__
    # Failure of a later source page must not prevent already durable requests
    # from reaching the receiver in this run.
    stage(db)
    receipts.deliver(db, post, get)
    reconcile(db)
    return collection_error


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['poll', 'status'])
    p.add_argument('--queue', required=True)
    p.add_argument('--config')
    args = p.parse_args()
    import fcntl
    lock_path = Path(args.queue + '.lock')
    if lock_path.is_symlink():
        raise ValueError('lock_symlink')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = source.connect(args.queue)
        receipts.setup(db)
        error = None
        if args.action == 'poll':
            path = Path(args.config)
            if path.is_symlink() or path.stat().st_mode & 0o077:
                raise ValueError('config_permissions')
            config = json.loads(path.read_text())
            if config.get('user_id') != '450826':
                raise ValueError('wrong_user')
            source_headers = {'X-Api-User-Id': config['user_id'], 'Authorization': 'Bearer ' + config['api_key']}
            receiver_headers = {'X-Intake-Token': config['crm_token'], 'Content-Type': 'application/json'}
            def fetch(path, params):
                url = source.API + path + ('?' + urllib.parse.urlencode(params) if params else '')
                return source.http_json(url, source_headers)
            error = cycle(db, fetch,
                          lambda body: source.http_json(ENDPOINT, receiver_headers, body),
                          lambda rid: source.http_json(ENDPOINT + '/receipts/' + rid, receiver_headers),
                          source.utcnow())
        state = receipts.status(db)
        original = source.status(db)
        print(json.dumps({'states': original, 'receipts': state, 'collection_error': error}))
        if error or any(count for key, count in state.items() if key != 'delivered') or any(original.get(k) for k in ('review', 'sending', 'uncertain')):
            return 2
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'error_type': type(exc).__name__}), file=sys.stderr)
        sys.exit(1)
