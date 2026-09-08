"""Private producer outbox for intake/v1. Only a verified GET confirms a lead.

Callers hold a process lock and retain source data. This module never deletes
rows or sends mail. POST retries use the exact durably stored envelope.
"""
import hashlib
import json
import re


def setup(db):
    db.execute('''CREATE TABLE IF NOT EXISTS receipt_outbox (
        namespace TEXT NOT NULL, delivery_id TEXT NOT NULL, payload TEXT NOT NULL,
        wire_sha256 TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
        receipt_id TEXT, receipt_sha256 TEXT, lead_id INTEGER,
        last_error TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(namespace,delivery_id))''')
    db.commit()


def enqueue(db, payload):
    """Participates in caller's transaction; does not commit source watermark."""
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(raw.encode()).hexdigest()
    key = payload['namespace'], payload['delivery_id']
    prior = db.execute('SELECT wire_sha256 FROM receipt_outbox WHERE namespace=? AND delivery_id=?', key).fetchone()
    if prior and prior[0] != digest:
        raise ValueError('immutable_delivery_conflict')
    db.execute('INSERT OR IGNORE INTO receipt_outbox(namespace,delivery_id,payload,wire_sha256) VALUES(?,?,?,?)',
               (*key, raw, digest))


def receiver_hash(payload):
    """Intake v1 canonical digest, including schema defaults, not raw wire SHA.

    Contract drift is checked against a fixture produced by the actual receiver.
    File bytes are represented by their verified metadata in the receiver digest.
    """
    lead = dict.fromkeys(('name', 'company', 'region', 'product', 'message',
                         'utm_source', 'utm_medium', 'utm_campaign', 'landing_url'), '')
    lead.update(phone=None, email=None)
    lead.update(payload['lead'])
    for key in ('phone', 'email'):
        if lead[key] is not None:
            value = lead[key].strip()
            lead[key] = (value.lower() if key == 'email' else value) or None
    normal = dict(subject='', message_id='', source_url='', template_id=None, tender_id=None, lot_id=None)
    normal.update({k: v for k, v in payload.items() if k not in ('lead', 'files')})
    normal['identity_namespace'] = payload.get('identity_namespace') or payload['namespace']
    normal['lead'] = lead
    normal['files'] = [dict(file_id=f['file_id'], filename=f['filename'], size_bytes=f['size_bytes'],
                            sha256=f['sha256'], content_type=f['data_url'][5:].split(';', 1)[0])
                       for f in sorted(payload.get('files', []), key=lambda f: f['file_id'])]
    raw = json.dumps(normal, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def validate_receipt(value, payload, known_id=None, known_hash=None):
    if not isinstance(value, dict):
        raise ValueError('invalid_receipt')
    for field in ('namespace', 'source_id', 'delivery_id'):
        if value.get(field) != payload[field]:
            raise ValueError('receipt_identity_mismatch')
    if value.get('identity_namespace') != (payload.get('identity_namespace') or payload['namespace']):
        raise ValueError('receipt_identity_mismatch')
    rid, digest = value.get('receipt_id'), value.get('payload_sha256')
    if not isinstance(rid, str) or not re.fullmatch('[a-f0-9]{32}', rid):
        raise ValueError('invalid_receipt_id')
    if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
        raise ValueError('invalid_receipt_hash')
    if digest != receiver_hash(payload):
        raise ValueError('receipt_payload_mismatch')
    if (known_id and rid != known_id) or (known_hash and digest != known_hash):
        raise ValueError('receipt_changed')
    if value.get('status') not in ('queued', 'delivered', 'failed', 'unavailable'):
        raise ValueError('invalid_receipt_status')
    files = value.get('files')
    expected = payload.get('files', [])
    if not isinstance(files, list) or len(files) != len(expected):
        raise ValueError('receipt_files_mismatch')
    actual = {f.get('file_id'): f for f in files if isinstance(f, dict)}
    if len(actual) != len(files):
        raise ValueError('receipt_files_mismatch')
    for file in expected:
        match = actual.get(file['file_id'], {})
        if any(match.get(k) != file[k] for k in ('filename', 'size_bytes', 'sha256')):
            raise ValueError('receipt_files_mismatch')
        if value['status'] == 'delivered' and (type(match.get('attachment_id')) is not int or match['attachment_id'] <= 0):
            raise ValueError('missing_attachment_id')
    if value['status'] == 'delivered' and (type(value.get('lead_id')) is not int or value['lead_id'] <= 0):
        raise ValueError('missing_lead_id')
    return rid, digest


def deliver(db, post, get, limit=50):
    """Replays a bounded batch. Error details exclude raw bodies and secrets."""
    rows = db.execute('''SELECT namespace,delivery_id,payload,wire_sha256,receipt_id,receipt_sha256
        FROM receipt_outbox WHERE state!='delivered' ORDER BY attempts, rowid LIMIT ?''', (limit,)).fetchall()
    confirmed = 0
    for namespace, delivery_id, raw, wire_hash, rid, digest in rows:
        key = namespace, delivery_id
        try:
            if hashlib.sha256(raw.encode()).hexdigest() != wire_hash:
                raise ValueError('local_payload_corrupted')
            payload = json.loads(raw)
            with db:
                db.execute("UPDATE receipt_outbox SET state='sending',attempts=attempts+1 WHERE namespace=? AND delivery_id=?", key)
            # A lost POST response is safe to replay because delivery_id and the
            # immutable envelope are committed before the network request.
            result = post(payload)
            rid, digest = validate_receipt(result, payload, rid, digest)
            with db:
                db.execute('UPDATE receipt_outbox SET receipt_id=?,receipt_sha256=?,state=? WHERE namespace=? AND delivery_id=?',
                           (rid, digest, 'queued', *key))
            result = get(rid)
            validate_receipt(result, payload, rid, digest)
            done = result['status'] == 'delivered'
            with db:
                db.execute('UPDATE receipt_outbox SET state=?,lead_id=?,last_error=? WHERE namespace=? AND delivery_id=?',
                           ('delivered' if done else result['status'], result.get('lead_id') if done else None,
                            '' if done else 'receiver_' + result['status'], *key))
            confirmed += int(done)
        except Exception as exc:
            # Known local validation errors contain no source text; HTTP and
            # unexpected exceptions expose only their type.
            reason = str(exc) if type(exc) is ValueError and str(exc) in {
                'local_payload_corrupted', 'invalid_receipt', 'receipt_identity_mismatch',
                'receipt_payload_mismatch',
                'invalid_receipt_id', 'invalid_receipt_hash', 'receipt_changed',
                'invalid_receipt_status', 'receipt_files_mismatch', 'missing_attachment_id', 'missing_lead_id'
            } else type(exc).__name__
            with db:
                db.execute("UPDATE receipt_outbox SET state='retry',last_error=? WHERE namespace=? AND delivery_id=?", (reason, *key))
    return confirmed


def status(db):
    return dict(db.execute('SELECT state,count(*) FROM receipt_outbox GROUP BY state'))
