"""Read-only IMAP -> private MIME queue -> verified CRM receipt.

Not deployed. Real mailbox/Legat classification acceptance is still required.
No SMTP or modification of messages. Unknown mail remains explicitly reviewable.
"""
import argparse
import imaplib
import json
import os
import ssl
import sys
from pathlib import Path

import mail_receipts
import mail_stage
import receipt_queue
from mottor_bridge import http_json

ENDPOINT = 'http://127.0.0.1:8000/integrations/intake/v1'


def setup(db):
    receipt_queue.setup(db)
    db.execute('''CREATE TABLE IF NOT EXISTS mail_preparation (
        identity TEXT PRIMARY KEY, decision TEXT NOT NULL, reason TEXT NOT NULL,
        delivery_id TEXT)''')
    db.commit()


def prepare_pending(db, limit=50):
    rows = db.execute('''SELECT m.identity,m.uid,m.reason,m.raw FROM messages m
        LEFT JOIN mail_preparation p ON p.identity=m.identity
        WHERE p.identity IS NULL ORDER BY m.uid LIMIT ?''', (limit,)).fetchall()
    validity = mail_stage.get_meta(db, 'uidvalidity')
    for identity, uid, old_reason, raw in rows:
        payload = None
        reason = old_reason
        if old_reason not in ('message_identity_conflict', 'oversized_original_in_mailbox', 'parse_failed'):
            try:
                payload, reason = mail_receipts.prepare(raw, validity, uid)
            except Exception:
                reason = 'message_prepare_failed'
        with db:
            if payload is not None:
                receipt_queue.enqueue(db, payload)
            decision = 'v1_pending' if payload is not None else 'review'
            db.execute('INSERT INTO mail_preparation VALUES(?,?,?,?)',
                       (identity, decision, reason or '', payload['delivery_id'] if payload else None))
            db.execute('UPDATE messages SET state=?,reason=? WHERE identity=?', (decision, reason or '', identity))


def reconcile(db):
    with db:
        db.execute('''UPDATE messages SET state='delivered' WHERE state='v1_pending'
            AND EXISTS(SELECT 1 FROM mail_preparation p JOIN receipt_outbox r
              ON r.namespace='admin@enersys.by' AND r.delivery_id=p.delivery_id
              WHERE p.identity=messages.identity AND r.state='delivered' AND r.lead_id>0)''')


def status(db):
    return {'messages': dict(db.execute('SELECT state,count(*) FROM messages GROUP BY state')),
            'review_reasons': dict(db.execute("SELECT reason,count(*) FROM messages WHERE state='review' GROUP BY reason")),
            'receipts': receipt_queue.status(db)}


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['init', 'poll', 'status'])
    p.add_argument('--queue', required=True)
    p.add_argument('--config')
    args = p.parse_args()
    import fcntl
    lock_path = Path(args.queue + '.lock')
    if lock_path.is_symlink():
        raise ValueError('lock_symlink')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = mail_stage.open_queue(args.queue)
        setup(db)
        error = None
        if args.action != 'status':
            path = Path(args.config)
            if path.is_symlink() or path.stat().st_mode & 0o077:
                raise ValueError('config_permissions')
            config = json.loads(path.read_text())
            if config.get('username') != 'admin@enersys.by':
                raise ValueError('wrong_mailbox')
            try:
                with imaplib.IMAP4_SSL('imap.yandex.ru', 993, ssl_context=ssl.create_default_context(), timeout=30) as client:
                    client.login(config['username'], config['password'])
                    action = mail_stage.initialize if args.action == 'init' else mail_stage.poll
                    action(db, client)
            except Exception as exc:
                error = type(exc).__name__
            if args.action == 'poll':
                prepare_pending(db)
                headers = {'X-Intake-Token': config['crm_token'], 'Content-Type': 'application/json'}
                receipt_queue.deliver(db, lambda body: http_json(ENDPOINT, headers, body),
                                      lambda rid: http_json(ENDPOINT + '/receipts/' + rid, headers))
                reconcile(db)
        result = status(db)
        result['collection_error'] = error
        print(json.dumps(result))
        if error or result['review_reasons'] or any(n for key, n in result['receipts'].items() if key != 'delivered'):
            return 2
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'error_type': type(exc).__name__}), file=sys.stderr)
        sys.exit(1)
