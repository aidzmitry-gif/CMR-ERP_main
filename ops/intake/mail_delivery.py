"""Read-only IMAP -> private MIME queue -> verified CRM receipt.

Not deployed. Real mailbox/Legat classification acceptance is still required.
No SMTP or modification of messages. Unknown mail remains explicitly reviewable.
"""
import argparse
import hashlib
import imaplib
import json
import os
import re
import ssl
import sys
from pathlib import Path

import mail_receipts
import mail_stage
import receipt_queue
from mottor_bridge import http_json

ENDPOINT = 'http://127.0.0.1:8000/integrations/intake/v1'
BATCH_BLOCKED_SOURCE_REASONS = frozenset({
    'message_identity_conflict', 'oversized_original_in_mailbox', 'parse_failed',
})
BATCH_ALLOWED_REVIEW_REASONS = frozenset({
    'procurement_requires_source_mapping', 'legat_requires_verified_tender_parser',
})
BATCH_SHA256_RE = re.compile(r'[0-9a-f]{64}\Z')
BATCH_RECEIPT_ID_RE = re.compile(r'[a-f0-9]{32}\Z')


def setup(db):
    receipt_queue.setup(db)
    db.execute('''CREATE TABLE IF NOT EXISTS mail_preparation (
        identity TEXT PRIMARY KEY, decision TEXT NOT NULL, reason TEXT NOT NULL,
        delivery_id TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS mail_preparation_batches (
        source_identity TEXT PRIMARY KEY, expected_raw_sha256 TEXT NOT NULL,
        manifest_sha256 TEXT NOT NULL, expected_children INTEGER NOT NULL,
        state TEXT NOT NULL DEFAULT 'prepared')''')
    db.execute('''CREATE TABLE IF NOT EXISTS mail_preparation_batch_children (
        source_identity TEXT NOT NULL, namespace TEXT NOT NULL, source_id TEXT NOT NULL,
        delivery_id TEXT NOT NULL, wire_sha256 TEXT NOT NULL, receiver_sha256 TEXT NOT NULL,
        PRIMARY KEY(namespace, delivery_id))''')
    db.commit()


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _wire_digest(payload):
    raw = _canonical_json(payload)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _manifest_digest(children):
    fields = ('namespace', 'source_id', 'delivery_id', 'wire_sha256', 'receiver_sha256')
    manifest = [
        {field: child[field] for field in fields}
        for child in sorted(children, key=lambda child: tuple(child[field] for field in fields))
    ]
    return hashlib.sha256(_canonical_json(manifest).encode('utf-8')).hexdigest()


def _manifest_matches(children, expected):
    try:
        return _manifest_digest(children) == expected
    except (KeyError, TypeError, ValueError):
        return False


def _batch_children_from_envelopes(envelopes):
    if isinstance(envelopes, (str, bytes, bytearray, dict)):
        raise ValueError('batch_invalid_envelopes')
    try:
        payloads = list(envelopes)
    except TypeError as exc:
        raise ValueError('batch_invalid_envelopes') from exc
    if not payloads:
        raise ValueError('batch_empty')

    children = []
    seen = set()
    for payload in payloads:
        if not isinstance(payload, dict):
            raise ValueError('batch_invalid_envelope')
        try:
            identity = tuple(payload[field] for field in ('namespace', 'source_id', 'delivery_id'))
            if any(not isinstance(value, str) or not value for value in identity):
                raise ValueError('batch_invalid_envelope')
            if (identity[0], identity[2]) in seen:
                raise ValueError('batch_duplicate_delivery')
            wire_sha256 = _wire_digest(payload)
            receiver_sha256 = receipt_queue.receiver_hash(payload)
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) in {
                    'batch_invalid_envelope', 'batch_duplicate_delivery'}:
                raise
            raise ValueError('batch_invalid_envelope') from exc
        seen.add((identity[0], identity[2]))
        children.append({
            'namespace': identity[0], 'source_id': identity[1], 'delivery_id': identity[2],
            'wire_sha256': wire_sha256, 'receiver_sha256': receiver_sha256, 'payload': payload,
        })
    return children, _manifest_digest(children)


def _load_batch_source(db, source_identity, expected_raw_sha256):
    if (not isinstance(source_identity, str) or not source_identity or
            not isinstance(expected_raw_sha256, str) or
            not BATCH_SHA256_RE.fullmatch(expected_raw_sha256.casefold())):
        raise ValueError('batch_invalid_source')
    expected_raw_sha256 = expected_raw_sha256.casefold()
    row = db.execute('SELECT state,reason,raw FROM messages WHERE identity=?',
                     (source_identity,)).fetchone()
    if not row:
        raise ValueError('batch_source_missing')
    state, reason, raw = row
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise ValueError('batch_source_raw_invalid')
    raw_sha256 = hashlib.sha256(bytes(raw)).hexdigest()
    if raw_sha256 != expected_raw_sha256:
        raise ValueError('batch_source_raw_mismatch')
    return state, reason or ''


def _batch_source_is_allowed(db, source_identity, state, reason, *, allow_delivered=False):
    if state not in ('review', 'v1_batch_pending') and not (allow_delivered and state == 'delivered'):
        raise ValueError('batch_source_not_eligible')
    preparation = db.execute(
        'SELECT decision,reason FROM mail_preparation WHERE identity=?',
        (source_identity,),
    ).fetchone()
    reasons = {value for value in (reason, preparation[1] if preparation else '') if value}
    if reasons & BATCH_BLOCKED_SOURCE_REASONS:
        raise ValueError('batch_source_blocked')
    if preparation and preparation[1] != reason:
        raise ValueError('batch_source_reason_mismatch')
    if preparation:
        decision = preparation[0]
        if decision == 'review':
            allowed = reasons and reasons <= BATCH_ALLOWED_REVIEW_REASONS
        elif decision == 'v1_batch_pending':
            allowed = reasons <= BATCH_ALLOWED_REVIEW_REASONS
        else:
            allowed = False
    else:
        allowed = state != 'delivered' and reasons <= BATCH_ALLOWED_REVIEW_REASONS
    if not allowed:
        raise ValueError('batch_source_not_eligible')
    return preparation


def _batch_child_rows(db, source_identity):
    rows = db.execute('''SELECT namespace,source_id,delivery_id,wire_sha256,receiver_sha256
        FROM mail_preparation_batch_children WHERE source_identity=?''', (source_identity,)).fetchall()
    return [dict(namespace=row[0], source_id=row[1], delivery_id=row[2],
                 wire_sha256=row[3], receiver_sha256=row[4]) for row in rows]


def _validate_batch_outbox_child(db, child, require_delivered=False):
    row = db.execute('''SELECT payload,wire_sha256,state,receipt_id,receipt_sha256,lead_id
        FROM receipt_outbox WHERE namespace=? AND delivery_id=?''',
                     (child['namespace'], child['delivery_id'])).fetchone()
    if not row:
        raise ValueError('batch_child_missing')
    payload_raw, wire_sha256, state, receipt_id, receipt_sha256, lead_id = row
    if (not isinstance(payload_raw, str) or wire_sha256 != child['wire_sha256'] or
            hashlib.sha256(payload_raw.encode('utf-8')).hexdigest() != wire_sha256):
        raise ValueError('batch_child_payload_mismatch')
    try:
        payload = json.loads(payload_raw)
        if not isinstance(payload, dict) or any(payload.get(field) != child[field]
                                                for field in ('namespace', 'source_id', 'delivery_id')):
            raise ValueError('batch_child_identity_mismatch')
        if _wire_digest(payload) != child['wire_sha256'] or receipt_queue.receiver_hash(payload) != child['receiver_sha256']:
            raise ValueError('batch_child_payload_mismatch')
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('batch_child_payload_mismatch') from exc
    if require_delivered and state != 'delivered':
        raise ValueError('batch_child_not_delivered')
    if state == 'delivered':
        if (not isinstance(receipt_id, str) or not BATCH_RECEIPT_ID_RE.fullmatch(receipt_id) or
                type(lead_id) is not int or lead_id <= 0):
            raise ValueError('batch_child_receipt_incomplete')
        if receipt_sha256 != child['receiver_sha256']:
            raise ValueError('batch_child_receipt_mismatch')


def _validate_existing_batch(db, batch, source_identity, expected_raw_sha256, children, manifest_sha256):
    if (batch[1] != expected_raw_sha256 or batch[2] != manifest_sha256 or
            batch[3] != len(children)):
        raise ValueError('batch_immutable_conflict')
    stored_children = _batch_child_rows(db, source_identity)
    fields = ('namespace', 'source_id', 'delivery_id', 'wire_sha256', 'receiver_sha256')
    if (len(stored_children) != len(children) or
            {tuple(child[field] for field in fields) for child in stored_children} !=
            {tuple(child[field] for field in fields) for child in children} or
            not _manifest_matches(stored_children, manifest_sha256)):
        raise ValueError('batch_immutable_conflict')
    for child in stored_children:
        _validate_batch_outbox_child(db, child, require_delivered=batch[4] == 'delivered')
    return {
        'source_identity': source_identity, 'expected_raw_sha256': expected_raw_sha256,
        'manifest_sha256': manifest_sha256, 'child_count': len(children), 'state': batch[4],
    }


def prepare_batch(db, source_identity, expected_raw_sha256, envelopes):
    """Atomically enqueue a manifest from a separately verified source adapter.

    ``envelopes`` are already prepared child payloads. Legat/template identity is
    never guessed here; the original source MIME remains in ``messages``.
    The caller must not hold an open transaction; this function takes a
    ``BEGIN IMMEDIATE`` lock before reading source or delivery ownership.
    """
    if (not isinstance(expected_raw_sha256, str) or
            not BATCH_SHA256_RE.fullmatch(expected_raw_sha256.casefold())):
        raise ValueError('batch_invalid_source')
    expected_raw_sha256 = expected_raw_sha256.casefold()
    children, manifest_sha256 = _batch_children_from_envelopes(envelopes)
    if db.in_transaction:
        raise ValueError('batch_transaction_active')
    db.execute('BEGIN IMMEDIATE')
    try:
        state, reason = _load_batch_source(db, source_identity, expected_raw_sha256)
        batch = db.execute('''SELECT source_identity,expected_raw_sha256,manifest_sha256,
            expected_children,state FROM mail_preparation_batches WHERE source_identity=?''',
                           (source_identity,)).fetchone()
        preparation = _batch_source_is_allowed(
            db, source_identity, state, reason,
            allow_delivered=batch is not None and batch[4] == 'delivered')
        if batch:
            result = _validate_existing_batch(db, batch, source_identity, expected_raw_sha256,
                                              children, manifest_sha256)
            db.commit()
            return result
        for child in children:
            prior = db.execute('''SELECT source_identity FROM mail_preparation_batch_children
                WHERE namespace=? AND delivery_id=?''',
                               (child['namespace'], child['delivery_id'])).fetchone()
            if prior:
                raise ValueError('batch_delivery_rebind')
            prior = db.execute('''SELECT 1 FROM receipt_outbox WHERE namespace=? AND delivery_id=?''',
                               (child['namespace'], child['delivery_id'])).fetchone()
            if prior:
                raise ValueError('batch_delivery_conflict')
        db.execute('''INSERT INTO mail_preparation_batches
            (source_identity,expected_raw_sha256,manifest_sha256,expected_children,state)
            VALUES(?,?,?,?,?)''',
                   (source_identity, expected_raw_sha256, manifest_sha256, len(children), 'prepared'))
        for child in children:
            receipt_queue.enqueue(db, child['payload'])
            db.execute('''INSERT INTO mail_preparation_batch_children
                (source_identity,namespace,source_id,delivery_id,wire_sha256,receiver_sha256)
                VALUES(?,?,?,?,?,?)''',
                       (source_identity, child['namespace'], child['source_id'], child['delivery_id'],
                        child['wire_sha256'], child['receiver_sha256']))
        if preparation is None:
            db.execute('INSERT INTO mail_preparation VALUES(?,?,?,?)',
                       (source_identity, 'v1_batch_pending', reason, None))
        db.execute("UPDATE messages SET state='v1_batch_pending' WHERE identity=?", (source_identity,))
        result = {
            'source_identity': source_identity, 'expected_raw_sha256': expected_raw_sha256,
            'manifest_sha256': manifest_sha256, 'child_count': len(children), 'state': 'prepared',
        }
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def prepare_pending(db, limit=50):
    rows = db.execute('''SELECT m.identity,m.uid,m.reason,m.raw FROM messages m
        LEFT JOIN mail_preparation p ON p.identity=m.identity
        LEFT JOIN mail_preparation_batches b ON b.source_identity=m.identity
        WHERE p.identity IS NULL AND b.source_identity IS NULL ORDER BY m.uid LIMIT ?''', (limit,)).fetchall()
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


def _reconcile_batch(db, batch):
    source_identity, expected_raw_sha256, manifest_sha256, expected_children, state = batch
    if state == 'delivered':
        return
    try:
        source_state, source_reason = _load_batch_source(db, source_identity, expected_raw_sha256)
        _batch_source_is_allowed(db, source_identity, source_state, source_reason)
    except ValueError:
        return
    children = _batch_child_rows(db, source_identity)
    fields = ('namespace', 'source_id', 'delivery_id', 'wire_sha256', 'receiver_sha256')
    if (len(children) != expected_children or not _manifest_matches(children, manifest_sha256) or
            any(not all(isinstance(child[field], str) and child[field] for field in fields)
                for child in children)):
        return
    try:
        for child in children:
            _validate_batch_outbox_child(db, child, require_delivered=True)
    except ValueError:
        return
    db.execute("UPDATE messages SET state='delivered' WHERE identity=?", (source_identity,))
    db.execute("UPDATE mail_preparation_batches SET state='delivered' WHERE source_identity=?",
               (source_identity,))


def reconcile(db):
    with db:
        db.execute('''UPDATE messages SET state='delivered' WHERE state='v1_pending'
            AND NOT EXISTS(SELECT 1 FROM mail_preparation_batches b
              WHERE b.source_identity=messages.identity)
            AND EXISTS(SELECT 1 FROM mail_preparation p JOIN receipt_outbox r
              ON r.namespace='admin@enersys.by' AND r.delivery_id=p.delivery_id
              WHERE p.identity=messages.identity AND r.state='delivered' AND r.lead_id>0)''')
        batches = db.execute('''SELECT source_identity,expected_raw_sha256,manifest_sha256,
            expected_children,state FROM mail_preparation_batches WHERE state!='delivered'
            ORDER BY source_identity''').fetchall()
        for batch in batches:
            _reconcile_batch(db, batch)


def _batch_status(db):
    counts = {'pending': 0, 'blocked': 0, 'delivered': 0}
    rows = db.execute('''SELECT source_identity,expected_raw_sha256,manifest_sha256,
        expected_children,state
        FROM mail_preparation_batches''').fetchall()
    for batch in rows:
        source_identity, expected_raw_sha256, manifest_sha256, _, state = batch
        try:
            source_state, source_reason = _load_batch_source(db, source_identity, expected_raw_sha256)
            _batch_source_is_allowed(
                db, source_identity, source_state, source_reason,
                allow_delivered=state == 'delivered')
            if state == 'delivered' and source_state != 'delivered':
                raise ValueError('batch_source_not_delivered')
            children = _batch_child_rows(db, source_identity)
            _validate_existing_batch(db, batch, source_identity, expected_raw_sha256,
                                     children, manifest_sha256)
        except ValueError:
            counts['blocked'] += 1
        else:
            counts['delivered' if state == 'delivered' else 'pending'] += 1
    return {key: value for key, value in counts.items() if value}


def status(db):
    return {'messages': dict(db.execute('SELECT state,count(*) FROM messages GROUP BY state')),
            'review_reasons': dict(db.execute("SELECT reason,count(*) FROM messages WHERE state='review' GROUP BY reason")),
            'receipts': receipt_queue.status(db), 'batches': _batch_status(db)}


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
        if (error or result['review_reasons'] or
                any(n for key, n in result['receipts'].items() if key != 'delivered') or
                result['batches'].get('pending', 0) or result['batches'].get('blocked', 0)):
            return 2
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'error_type': type(exc).__name__}), file=sys.stderr)
        sys.exit(1)
