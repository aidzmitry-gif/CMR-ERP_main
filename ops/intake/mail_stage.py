"""Read-only IMAP intake staging. No SMTP, CRM writes or mailbox mutations.

First initialize a new-message boundary, then poll into a private SQLite queue.
Credentials are read from a private JSON file, never printed. Candidate messages
require review before any separate delivery worker may consume them.
"""
import argparse
import hashlib
import imaplib
import json
import os
import re
import sqlite3
import ssl
from email import policy
from email.parser import BytesParser
from pathlib import Path

# MIME base64 overhead must not reject an otherwise supported 10 MiB attachment.
MAX_BYTES = 32 * 1024 * 1024
MAX_BATCH = 50


def parse_message(raw):
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    body = msg.get_body(preferencelist=('plain',))
    text = body.get_content() if body else ''
    subject = str(msg.get('Subject', ''))
    sender = str(msg.get('From', ''))
    recipients = ' '.join(str(msg.get(k, '')) for k in
                          ('To', 'Cc', 'Delivered-To', 'X-Original-To'))
    attachments = [p.get_filename() or 'attachment' for p in msg.iter_attachments()]
    key = str(msg.get('Message-ID', '')).strip()
    if not key:
        key = 'sha256:' + hashlib.sha256(raw).hexdigest()
    combined = (subject + '\n' + text).casefold()
    # These are review categories, not destructive rules or silent exclusions.
    state, reason = 'review', 'unclassified'
    if 'order@microchips.by' in recipients.casefold():
        reason = 'possible_site_copy'
    elif (msg.get('List-ID') or msg.get('List-Unsubscribe') or
          str(msg.get('Precedence', '')).casefold() in ('bulk', 'list') or
          str(msg.get('Auto-Submitted', 'no')).casefold() != 'no'):
        reason = 'automatic_or_list_message'
    elif any(x in combined for x in ('тендер', 'закупк', 'маркетинговое исследование')):
        reason = 'procurement_requires_source_mapping'
    elif any(x in combined for x in ('прошу', 'просим', 'нужен', 'нужны', 'запрос', 'заявка')):
        if any(x in combined for x in ('аккумулятор', 'батаре', 'элемент питан', 'акб')):
            state, reason = 'candidate', 'customer_request_candidate'
    if attachments:
        state, reason = 'review', 'attachments_require_processing'
    if msg.defects:
        state, reason = 'review', 'message_parse_defects'
    return key, state, reason, {
        'from': sender, 'subject': subject, 'text': text,
        'message_id': str(msg.get('Message-ID', '')),
        'in_reply_to': str(msg.get('In-Reply-To', '')),
        'references': str(msg.get('References', '')),
        'attachments': attachments,
    }


def open_queue(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('queue_symlink_not_allowed')
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    if os.name != 'nt' and path.stat().st_mode & 0o077:
        raise ValueError('queue_requires_private_permissions')
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)')
    db.execute('''CREATE TABLE IF NOT EXISTS messages (
        identity TEXT PRIMARY KEY, uid INTEGER NOT NULL, state TEXT NOT NULL,
        reason TEXT NOT NULL, payload TEXT NOT NULL, raw BLOB NOT NULL)''')
    return db


def get_meta(db, key):
    row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return row[0] if row else None


def set_meta(db, key, value):
    db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, str(value)))


def select_mailbox(client):
    status, _ = client.select('INBOX', readonly=True)
    if status != 'OK':
        raise RuntimeError('inbox_unavailable')
    values = {}
    for name in ('UIDVALIDITY', 'UIDNEXT'):
        _, data = client.response(name)
        if not data or not data[0] or not data[0].isdigit():
            raise RuntimeError('missing_' + name)
        values[name] = int(data[0])
    return values


def initialize(db, client):
    if get_meta(db, 'uidvalidity') is not None:
        raise RuntimeError('already_initialized_do_not_reset')
    state = select_mailbox(client)
    with db:
        set_meta(db, 'uidvalidity', state['UIDVALIDITY'])
        set_meta(db, 'last_uid', state['UIDNEXT'] - 1)
    return {'initialized': True, 'history_imported': False}


def stage(db, uid, raw):
    try:
        identity, state, reason, payload = parse_message(raw)
    except (ValueError, TypeError, LookupError, UnicodeError):
        identity = 'sha256:' + hashlib.sha256(raw).hexdigest()
        state, reason, payload = 'review', 'parse_failed', {}
    if not payload.get('message_id', '').strip():
        identity = f"uid:{get_meta(db, 'uidvalidity')}:{uid}"
    prior = db.execute('SELECT raw FROM messages WHERE identity=?', (identity,)).fetchone()
    if prior is not None and prior[0] != raw:
        # A reused Message-ID must not silently erase a different request.
        identity = 'conflict:' + hashlib.sha256(identity.encode()).hexdigest() + ':' + hashlib.sha256(raw).hexdigest()
        state, reason = 'review', 'message_identity_conflict'
    # Exact repeats dedupe; changed identity content stays explicitly reviewable.
    db.execute('INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?)',
               (identity, uid, state, reason, json.dumps(payload, ensure_ascii=False), raw))


def poll(db, client):
    validity = get_meta(db, 'uidvalidity')
    if validity is None:
        raise RuntimeError('initialize_required_no_history_import')
    state = select_mailbox(client)
    if str(state['UIDVALIDITY']) != validity:
        raise RuntimeError('uidvalidity_changed_review_required')
    last = int(get_meta(db, 'last_uid'))
    upper = state['UIDNEXT'] - 1
    if upper <= last:
        return {'fetched': 0}
    status, data = client.uid('search', None, 'UID', f'{last + 1}:{upper}')
    if status != 'OK' or not data:
        raise RuntimeError('search_failed')
    uids = sorted({int(x) for x in data[0].split() if last < int(x) <= upper})[:MAX_BATCH]
    count = 0
    for uid in uids:
        status, sizes = client.uid('fetch', str(uid), '(RFC822.SIZE)')
        line = b' '.join(x for x in sizes or [] if isinstance(x, bytes))
        match = re.search(rb'RFC822.SIZE\s+(\d+)', line)
        if status != 'OK' or not match:
            raise RuntimeError('size_fetch_failed_watermark_preserved')
        if int(match[1]) > MAX_BYTES:
            # Preserve a visible review item; original remains in the mailbox.
            with db:
                db.execute('INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?)',
                           (f'oversize:{validity}:{uid}', uid, 'review',
                            'oversized_original_in_mailbox', '{}', b''))
                set_meta(db, 'last_uid', uid)
            count += 1
            continue
        status, parts = client.uid('fetch', str(uid), '(BODY.PEEK[])')
        raw = next((p[1] for p in parts or [] if isinstance(p, tuple)
                    and len(p) > 1 and isinstance(p[1], bytes)), None)
        if status != 'OK' or raw is None:
            raise RuntimeError('body_fetch_failed_watermark_preserved')
        if len(raw) > MAX_BYTES:
            raise RuntimeError('unexpected_message_size')
        with db:
            stage(db, uid, raw)
            set_meta(db, 'last_uid', uid)
        count += 1
    return {'fetched': count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'poll', 'status'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--queue', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        os.umask(0o077)
    with open_queue(args.queue) as db:
        if args.command == 'status':
            print(json.dumps(dict(db.execute('SELECT state, COUNT(*) FROM messages GROUP BY state'))))
            return
        if not args.config:
            parser.error('--config is required')
        if os.name != 'nt' and args.config.stat().st_mode & 0o077:
            raise ValueError('credential_file_requires_private_permissions')
        cfg = json.loads(args.config.read_text(encoding='utf-8'))
        if cfg.get('username') != 'admin@enersys.by':
            raise ValueError('unexpected_mailbox')
        with imaplib.IMAP4_SSL('imap.yandex.ru', 993, ssl_context=ssl.create_default_context(),
                              timeout=30) as client:
            client.login(cfg['username'], cfg['password'])
            operation = initialize if args.command == 'init' else poll
            print(json.dumps(operation(db, client)))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # IMAP errors can contain server text; do not print credentials or mail.
        print(json.dumps({'error_type': type(exc).__name__, 'operation_failed': True}))
        raise SystemExit(1) from None
