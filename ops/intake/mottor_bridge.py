"""New enersys.by requests: Mottor API -> durable queue -> existing CRM intake.

No Mottor mutations. Uncertain POST outcomes require reconciliation; never blindly
retry them. Existing CRM groups repeat requests by an open contact/company lead.
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = 'https://api.lpmotor.ru/v1/lead'
SITE = 1191119
LIMIT = 50
MAX_BODY = 4 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_json(url, headers, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
        raw = response.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            raise ValueError('response_too_large')
        return json.loads(raw)


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def timestamp(value):
    result = dt.datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('timestamp_without_timezone')
    return result.astimezone(dt.timezone.utc)


def connect(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('queue_symlink')
    if path.exists() and os.name == 'posix' and path.stat().st_mode & 0o077:
        raise ValueError('queue_permissions')
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    db.execute('''CREATE TABLE IF NOT EXISTS deliveries (
        source_id INTEGER PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL,
        observed_at TEXT NOT NULL, last_error TEXT NOT NULL DEFAULT '')''')
    db.commit()
    return db


def meta(db, key):
    row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return row[0] if row else None


def initialize(db, now):
    if meta(db, 'start'):
        raise ValueError('already_initialized')
    with db:
        for key in ('start', 'cursor'):
            db.execute('INSERT INTO meta VALUES (?, ?)', (key, now.isoformat()))


def validate_lead(lead, source_id=None):
    if not isinstance(lead, dict) or type(lead.get('id')) is not int or lead['id'] <= 0:
        raise ValueError('invalid_source_id')
    if source_id is not None and lead['id'] != source_id:
        raise ValueError('source_id_mismatch')
    page = lead.get('page') or {}
    if page.get('site_id') != SITE or (page.get('site') or {}).get('attached_domain') != 'enersys.by':
        raise ValueError('wrong_site')
    timestamp(lead['d_created'])


def collect(db, fetch, now):
    if not meta(db, 'start'):
        raise ValueError('not_initialized')
    # Reconcile the whole new-only interval: a source record may become visible
    # long after d_created. A moving five-minute window silently missed it.
    lower = timestamp(meta(db, 'start'))
    if now < timestamp(meta(db, 'cursor')):
        raise ValueError('clock_moved_backwards')
    offset, observed, expected, previous_id = 0, 0, None, 0
    while True:
        result = fetch('', {
            'site_id': SITE, 'limit': LIMIT, 'offset': offset,
            'sort_field[]': 'id', 'sort_dir[]': 'ASC',
            'd_create_start': lower.isoformat(), 'd_create_end': now.isoformat(),
        })
        rows = result.get('leads')
        total = result.get('count')
        if not isinstance(rows, list) or type(total) is not int or total < 0:
            raise ValueError('invalid_list_response')
        if expected is not None and total != expected:
            raise ValueError('source_changed_during_pagination')
        expected = total
        if len(rows) > LIMIT or offset + len(rows) > total:
            raise ValueError('invalid_pagination')
        for row in rows:
            validate_lead(row)
            if row['id'] <= previous_id:
                raise ValueError('source_ids_not_strictly_increasing')
            previous_id = row['id']
            created = timestamp(row['d_created'])
            if not lower <= created <= now:
                raise ValueError('source_ignored_date_filter')
            if db.execute('SELECT 1 FROM deliveries WHERE source_id=?', (row['id'],)).fetchone():
                continue
            detail = fetch('/' + str(row['id']), {})
            validate_lead(detail, row['id'])
            state = 'ignored' if detail.get('is_del') else 'pending'
            with db:
                db.execute('INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?, ?, ?)',
                           (row['id'], state, json.dumps(detail, ensure_ascii=False), now.isoformat(), ''))
            observed += 1
        offset += len(rows)
        if offset == total:
            break
        if not rows or offset >= 10000:
            raise ValueError('incomplete_pagination')
    with db:
        db.execute('UPDATE meta SET value=? WHERE key=?', (now.isoformat(), 'cursor'))
    return observed


def intake_payload(lead):
    validate_lead(lead)
    # Full source document retained in private queue and CRM note, including
    # form/history/cart fields and attachment URLs. No files are fetched here.
    body = json.dumps(lead, ensure_ascii=False, indent=2)
    if len(body.encode()) > 128 * 1024:
        raise ValueError('lead_requires_review_size')
    return {
        'name': lead.get('name') or '', 'phone': lead.get('phone') or '',
        'email': lead.get('email') or '', 'company': '',
        'product': 'Заявка enersys.by #' + str(lead['id']),
        'message': '[mottor:1191119:' + str(lead['id']) + ']\n' + body,
        'landing_url': 'https://enersys.by/',
    }


def deliver(db, send):
    sent = 0
    for source_id, raw in db.execute(
            "SELECT source_id,payload FROM deliveries WHERE state='pending' ORDER BY source_id LIMIT 50").fetchall():
        try:
            payload = intake_payload(json.loads(raw))
        except ValueError as exc:
            with db:
                db.execute("UPDATE deliveries SET state='review',last_error=? WHERE source_id=?",
                           (str(exc), source_id))
            continue
        # Persist before network IO: a crash after CRM commit cannot trigger
        # another POST. 'sending' is visibly unresolved on the next run.
        with db:
            db.execute("UPDATE deliveries SET state='sending' WHERE source_id=?", (source_id,))
        try:
            result = send(payload)
            if result.get('ok') is not True or result.get('source') != 'site':
                raise ValueError('unexpected_crm_ack')
        except Exception as exc:
            with db:
                db.execute("UPDATE deliveries SET state='uncertain',last_error=? WHERE source_id=?",
                           (type(exc).__name__, source_id))
            continue
        with db:
            db.execute("UPDATE deliveries SET state='accepted',last_error='' WHERE source_id=?", (source_id,))
        sent += 1
    return sent


def status(db):
    return dict(db.execute('SELECT state,count(*) FROM deliveries GROUP BY state'))


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['init', 'poll', 'status'])
    p.add_argument('--queue', required=True)
    p.add_argument('--config')
    args = p.parse_args()
    # Separate process lock held through collection and sending. systemd also
    # serializes the oneshot, but CLI invocations must be safe independently.
    import fcntl
    lock_path = Path(args.queue + '.lock')
    if lock_path.is_symlink():
        raise ValueError('lock_symlink')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = connect(args.queue)
        if args.action == 'init':
            initialize(db, utcnow())
        elif args.action == 'poll':
            config_path = Path(args.config)
            if config_path.is_symlink() or config_path.stat().st_mode & 0o077:
                raise ValueError('config_permissions')
            config = json.loads(config_path.read_text())
            if config.get('user_id') != '450826':
                raise ValueError('wrong_user')
            headers = {'X-Api-User-Id': config['user_id'],
                       'Authorization': 'Bearer ' + config['api_key'], 'Accept': 'application/json'}
            def fetch(path, params):
                url = API + path + ('?' + urllib.parse.urlencode(params) if params else '')
                return http_json(url, headers)
            def send(payload):
                return http_json('http://127.0.0.1:8000/integrations/web/lead',
                                 {'Content-Type': 'application/json'},
                                 dict(payload, token=config['crm_token']))
            collect(db, fetch, utcnow())
            deliver(db, send)
        counts = status(db)
        print(json.dumps({'states': counts, 'cursor': meta(db, 'cursor')}))
        if any(counts.get(k) for k in ('uncertain', 'sending', 'review')):
            return 2
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__}), file=sys.stderr)
        sys.exit(1)
