import hashlib
import json
import os
import sqlite3
import tempfile
import unittest

import mail_delivery as bridge
import mail_stage
import receipt_queue
from test_mail_receipts import message


def child_envelope(number, *, delivery_id=None, source_id=None):
    return {
        'namespace': 'admin@enersys.by',
        'source_id': source_id or f'legat-source-{number}',
        'delivery_id': delivery_id or f'legat-delivery-{number}',
        'subject': f'Лот {number}',
        'message_id': f'<legat-{number}@example.invalid>',
        'lead': {
            'name': 'Verified customer', 'email': 'customer@example.invalid',
            'product': f'Battery lot {number}', 'message': f'Quantity for lot {number}',
        },
        'files': [],
    }


class MailDelivery(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE messages(identity TEXT PRIMARY KEY,uid INTEGER NOT NULL,state TEXT NOT NULL,
              reason TEXT NOT NULL,payload TEXT NOT NULL,raw BLOB NOT NULL);''')
        mail_stage.set_meta(self.db, 'uidvalidity', '100')
        self.db.commit()
        bridge.setup(self.db)

    def tearDown(self):
        self.db.close()

    def stage_review_source(self, uid=1, message_id=None):
        msg = message()
        msg.replace_header('Subject', 'Тендер: verified source')
        if message_id is not None:
            msg.replace_header('Message-ID', message_id)
        raw = msg.as_bytes()
        with self.db:
            mail_stage.stage(self.db, uid, raw)
        bridge.prepare_pending(self.db)
        identity, state, reason = self.db.execute(
            'SELECT identity,state,reason FROM messages WHERE uid=?', (uid,)
        ).fetchone()
        self.assertEqual((state, reason), ('review', 'procurement_requires_source_mapping'))
        return identity, raw

    def batch_payloads(self, count=4, prefix='legat'):
        return [child_envelope(
            index, source_id=f'{prefix}-source-{index}',
            delivery_id=f'{prefix}-delivery-{index}'
        ) for index in range(1, count + 1)]

    def delivered_receipt(self, payload, lead_id=17):
        answer = {key: payload[key] for key in ('namespace', 'source_id', 'delivery_id')}
        answer.update(
            identity_namespace=payload['namespace'],
            receipt_id=hashlib.sha256(payload['delivery_id'].encode()).hexdigest()[:32],
            payload_sha256=receipt_queue.receiver_hash(payload),
            status='delivered', lead_id=lead_id,
            files=[dict(file, attachment_id=index + 1)
                   for index, file in enumerate(payload.get('files', []))],
        )
        return answer

    def mark_batch_children_delivered(self, source_identity, lead_id=17):
        rows = self.db.execute('''SELECT namespace,delivery_id,payload FROM receipt_outbox
            WHERE (namespace,delivery_id) IN (
              SELECT namespace,delivery_id FROM mail_preparation_batch_children
              WHERE source_identity=?)''', (source_identity,)).fetchall()
        with self.db:
            for namespace, delivery_id, raw in rows:
                payload = json.loads(raw)
                digest = receipt_queue.receiver_hash(payload)
                self.db.execute('''UPDATE receipt_outbox SET state='delivered',receipt_id=?,
                    receipt_sha256=?,lead_id=? WHERE namespace=? AND delivery_id=?''',
                                ('a' * 32, digest, lead_id, namespace, delivery_id))

    def reopen_database(self):
        reopened = sqlite3.connect(':memory:')
        self.db.backup(reopened)
        self.db.close()
        self.db = reopened
        bridge.setup(self.db)

    def test_mime_attachment_reaches_verified_receipt_without_deleting_original(self):
        msg = message()
        msg.add_attachment(b'%PDF-1.4 test', maintype='application', subtype='pdf', filename='request.pdf')
        raw = msg.as_bytes()
        with self.db:
            mail_stage.stage(self.db, 1, raw)
        bridge.prepare_pending(self.db)
        bridge.prepare_pending(self.db)
        payload = json.loads(self.db.execute('SELECT payload FROM receipt_outbox').fetchone()[0])
        answer = {k: payload[k] for k in ('namespace', 'source_id', 'delivery_id')}
        answer.update(identity_namespace=payload['namespace'], receipt_id='a'*32,
                      payload_sha256=receipt_queue.receiver_hash(payload), status='delivered', lead_id=17,
                      files=[dict(payload['files'][0], attachment_id=3)])
        self.assertEqual(receipt_queue.deliver(self.db, lambda _: answer, lambda _: answer), 1)
        bridge.reconcile(self.db)
        self.assertEqual(bridge.status(self.db)['messages'], {'delivered': 1})
        self.assertEqual(self.db.execute('SELECT raw FROM messages').fetchone()[0], raw)

    def test_reused_message_id_conflict_stays_reviewable(self):
        first, second = message(), message()
        second.set_content('Просим прислать другие аккумуляторы.')
        with self.db:
            mail_stage.stage(self.db, 1, first.as_bytes())
            mail_stage.stage(self.db, 2, second.as_bytes())
        bridge.prepare_pending(self.db)
        self.assertEqual(bridge.status(self.db)['receipts'], {'pending': 1})
        self.assertEqual(bridge.status(self.db)['review_reasons'], {'message_identity_conflict': 1})

    def test_list_mail_never_enqueues_as_client_request(self):
        msg = message()
        msg['List-Unsubscribe'] = '<mailto:example@example.invalid>'
        with self.db:
            mail_stage.stage(self.db, 1, msg.as_bytes())
        bridge.prepare_pending(self.db)
        self.assertEqual(bridge.status(self.db)['receipts'], {})
        self.assertEqual(bridge.status(self.db)['review_reasons'], {'automatic_or_list_message': 1})

    def test_four_lot_batch_partial_resume_reopen_and_idempotent(self):
        source_identity, raw = self.stage_review_source()
        expected = hashlib.sha256(raw).hexdigest()
        payloads = self.batch_payloads()
        prepared = bridge.prepare_batch(self.db, source_identity, expected, payloads)
        self.assertEqual(prepared['child_count'], 4)
        bridge.prepare_pending(self.db)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM receipt_outbox').fetchone()[0], 4)
        self.assertEqual(bridge.status(self.db)['batches'], {'pending': 1})
        repeated = bridge.prepare_batch(self.db, source_identity, expected, list(reversed(payloads)))
        self.assertEqual(repeated, prepared)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM receipt_outbox').fetchone()[0], 4)

        receipts = {}
        fail_once = {'value': True}

        def post(payload):
            if payload['delivery_id'] == 'legat-delivery-2' and fail_once['value']:
                fail_once['value'] = False
                raise RuntimeError('synthetic partial failure')
            answer = self.delivered_receipt(payload)
            receipts[answer['receipt_id']] = answer
            return answer

        def get(receipt_id):
            return receipts[receipt_id]

        self.assertEqual(receipt_queue.deliver(self.db, post, get), 3)
        bridge.reconcile(self.db)
        self.assertEqual(self.db.execute('SELECT state FROM messages').fetchone()[0],
                         'v1_batch_pending')
        self.reopen_database()
        self.assertEqual(receipt_queue.deliver(self.db, post, get), 1)
        bridge.reconcile(self.db)
        self.assertEqual(self.db.execute('SELECT state FROM messages').fetchone()[0], 'delivered')
        self.assertEqual(bridge.prepare_batch(self.db, source_identity, expected,
                                              list(reversed(payloads)))['state'], 'delivered')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM receipt_outbox').fetchone()[0], 4)

    def test_batch_empty_and_duplicate_delivery_rejected(self):
        source_identity, raw = self.stage_review_source()
        expected = hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(ValueError, 'batch_empty'):
            bridge.prepare_batch(self.db, source_identity, expected, [])
        payloads = self.batch_payloads(2)
        payloads[1]['delivery_id'] = payloads[0]['delivery_id']
        with self.assertRaisesRegex(ValueError, 'batch_duplicate_delivery'):
            bridge.prepare_batch(self.db, source_identity, expected, payloads)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM mail_preparation_batches').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM receipt_outbox').fetchone()[0], 0)

    def test_batch_immutable_set_payload_raw_and_second_source_rejected(self):
        source_identity, raw = self.stage_review_source()
        expected = hashlib.sha256(raw).hexdigest()
        payloads = self.batch_payloads()
        bridge.prepare_batch(self.db, source_identity, expected, payloads)
        with self.assertRaisesRegex(ValueError, 'batch_immutable_conflict'):
            bridge.prepare_batch(self.db, source_identity, expected, payloads[:3] + self.batch_payloads(1, 'other'))
        changed = [dict(payload) for payload in payloads]
        changed[0]['subject'] = 'changed payload'
        with self.assertRaisesRegex(ValueError, 'batch_immutable_conflict'):
            bridge.prepare_batch(self.db, source_identity, expected, changed)

        second_source = 'synthetic-second-source'
        with self.db:
            self.db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',
                            (second_source, 2, 'review', 'procurement_requires_source_mapping', '{}', raw))
        with self.assertRaisesRegex(ValueError, 'batch_delivery_rebind'):
            bridge.prepare_batch(self.db, second_source, expected, payloads)

        with self.db:
            self.db.execute('UPDATE messages SET raw=? WHERE identity=?', (raw + b'changed', source_identity))
        with self.assertRaisesRegex(ValueError, 'batch_source_raw_mismatch'):
            bridge.prepare_batch(self.db, source_identity, expected, payloads)

    def test_batch_enqueue_failure_rolls_back_manifest_and_outbox(self):
        source_identity, raw = self.stage_review_source()
        expected = hashlib.sha256(raw).hexdigest()
        payloads = self.batch_payloads()
        before = list(self.db.iterdump())
        original_enqueue = receipt_queue.enqueue
        calls = {'count': 0}

        def fail_on_second(db, payload):
            calls['count'] += 1
            original_enqueue(db, payload)
            if calls['count'] == 2:
                raise RuntimeError('synthetic enqueue failure')

        receipt_queue.enqueue = fail_on_second
        try:
            with self.assertRaisesRegex(RuntimeError, 'synthetic enqueue failure'):
                bridge.prepare_batch(self.db, source_identity, expected, payloads)
        finally:
            receipt_queue.enqueue = original_enqueue
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM mail_preparation_batches').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM mail_preparation_batch_children').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM receipt_outbox').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT state FROM messages').fetchone()[0], 'review')
        self.assertEqual(list(self.db.iterdump()), before)

    def test_batch_cancellation_rolls_back_manifest_and_outbox(self):
        source_identity, raw = self.stage_review_source()
        expected = hashlib.sha256(raw).hexdigest()
        payloads = self.batch_payloads()
        before = list(self.db.iterdump())
        original_enqueue = receipt_queue.enqueue
        for cancellation in (KeyboardInterrupt, SystemExit):
            calls = {'count': 0}

            def cancel_on_second(db, payload):
                calls['count'] += 1
                original_enqueue(db, payload)
                if calls['count'] == 2:
                    raise cancellation()

            receipt_queue.enqueue = cancel_on_second
            try:
                with self.assertRaises(cancellation):
                    bridge.prepare_batch(self.db, source_identity, expected, payloads)
            finally:
                receipt_queue.enqueue = original_enqueue
            self.assertFalse(self.db.in_transaction)
            self.db.commit()
            self.assertEqual(list(self.db.iterdump()), before)

    def test_batch_missing_child_and_tampered_receipt_never_reconcile(self):
        source_identity, raw = self.stage_review_source()
        expected = hashlib.sha256(raw).hexdigest()
        payloads = self.batch_payloads(prefix='missing')
        bridge.prepare_batch(self.db, source_identity, expected, payloads)
        with self.db:
            self.db.execute('''DELETE FROM mail_preparation_batch_children
                               WHERE source_identity=? AND delivery_id=?''',
                            (source_identity, payloads[0]['delivery_id']))
        self.mark_batch_children_delivered(source_identity)
        bridge.reconcile(self.db)
        self.assertEqual(self.db.execute('SELECT state FROM messages WHERE identity=?',
                                         (source_identity,)).fetchone()[0], 'v1_batch_pending')
        self.assertEqual(bridge.status(self.db)['batches'], {'blocked': 1})

        cases = (('receipt-hash', "UPDATE receipt_outbox SET receipt_sha256=? WHERE delivery_id=?",
                  ('0' * 64, 'receipt-hash-delivery-1')),
                 ('lead-id', "UPDATE receipt_outbox SET lead_id=? WHERE delivery_id=?",
                  (0, 'lead-id-delivery-1')),
                 ('receipt-id', "UPDATE receipt_outbox SET receipt_id=? WHERE delivery_id=?",
                  ('bad', 'receipt-id-delivery-1')))
        for prefix, statement, values in cases:
            identity, source_raw = self.stage_review_source(uid=len(prefix) + 10,
                                                              message_id=f'<{prefix}@example.invalid>')
            children = self.batch_payloads(prefix=prefix)
            bridge.prepare_batch(self.db, identity, hashlib.sha256(source_raw).hexdigest(), children)
            self.mark_batch_children_delivered(identity)
            with self.db:
                self.db.execute(statement, values)
            bridge.reconcile(self.db)
            self.assertEqual(self.db.execute('SELECT state FROM messages WHERE identity=?',
                                             (identity,)).fetchone()[0], 'v1_batch_pending')

        identity, source_raw = self.stage_review_source(uid=30,
                                                          message_id='<source-id@example.invalid>')
        children = self.batch_payloads(prefix='source-id')
        bridge.prepare_batch(self.db, identity, hashlib.sha256(source_raw).hexdigest(), children)
        row = self.db.execute('SELECT payload FROM receipt_outbox WHERE delivery_id=?',
                              (children[0]['delivery_id'],)).fetchone()
        tampered = json.loads(row[0])
        tampered['source_id'] = 'foreign-source-id'
        with self.db:
            self.db.execute('UPDATE receipt_outbox SET payload=? WHERE delivery_id=?',
                            (json.dumps(tampered, ensure_ascii=True, sort_keys=True,
                                        separators=(',', ':')), children[0]['delivery_id']))
        self.mark_batch_children_delivered(identity)
        bridge.reconcile(self.db)
        self.assertEqual(self.db.execute('SELECT state FROM messages WHERE identity=?',
                                         (identity,)).fetchone()[0], 'v1_batch_pending')

        identity, source_raw = self.stage_review_source(uid=31,
                                                          message_id='<post-only@example.invalid>')
        children = self.batch_payloads(1, prefix='post-only')
        bridge.prepare_batch(self.db, identity, hashlib.sha256(source_raw).hexdigest(), children)

        def post_only_post(payload):
            return self.delivered_receipt(payload)

        def post_only_get(_):
            raise RuntimeError('synthetic GET unavailable')

        self.assertEqual(receipt_queue.deliver(self.db, post_only_post, post_only_get), 0)
        bridge.reconcile(self.db)
        self.assertEqual(self.db.execute('SELECT state FROM messages WHERE identity=?',
                                         (identity,)).fetchone()[0], 'v1_batch_pending')

    def test_batch_orphan_manifest_child_never_reconciles(self):
        identity, raw = self.stage_review_source()
        children = self.batch_payloads(prefix='orphan')
        bridge.prepare_batch(self.db, identity, hashlib.sha256(raw).hexdigest(), children)
        child = children[0]
        with self.db:
            self.db.execute('''INSERT INTO mail_preparation_batch_children
                (source_identity,namespace,source_id,delivery_id,wire_sha256,receiver_sha256)
                VALUES(?,?,?,?,?,?)''',
                            (identity, child['namespace'], child['source_id'],
                             'orphan-delivery', bridge._wire_digest(child),
                             receipt_queue.receiver_hash(child)))
        self.mark_batch_children_delivered(identity)
        bridge.reconcile(self.db)
        self.assertEqual(self.db.execute('SELECT state FROM messages WHERE identity=?',
                                         (identity,)).fetchone()[0], 'v1_batch_pending')

    def test_all_delivered_batch_source_tamper_is_visible_as_blocked(self):
        identity, raw = self.stage_review_source()
        children = self.batch_payloads(prefix='raw-tamper')
        bridge.prepare_batch(self.db, identity, hashlib.sha256(raw).hexdigest(), children)
        self.mark_batch_children_delivered(identity)
        with self.db:
            self.db.execute('UPDATE messages SET raw=? WHERE identity=?', (raw + b'tampered', identity))
        bridge.reconcile(self.db)
        self.assertEqual(self.db.execute('SELECT state FROM messages WHERE identity=?',
                                         (identity,)).fetchone()[0], 'v1_batch_pending')
        self.assertEqual(bridge.status(self.db)['receipts'], {'delivered': 4})
        self.assertEqual(bridge.status(self.db)['batches'], {'blocked': 1})

        identity, raw = self.stage_review_source(uid=22, message_id='<reason-tamper@example.invalid>')
        children = self.batch_payloads(prefix='reason-tamper')
        bridge.prepare_batch(self.db, identity, hashlib.sha256(raw).hexdigest(), children)
        self.mark_batch_children_delivered(identity)
        with self.db:
            self.db.execute('UPDATE messages SET reason=? WHERE identity=?',
                            ('message_identity_conflict', identity))
        bridge.reconcile(self.db)
        self.assertEqual(bridge.status(self.db)['batches'], {'blocked': 2})

    def test_completed_batch_tamper_is_visible_as_blocked(self):
        cases = ('raw', 'reason', 'child', 'receipt')
        for index, tamper in enumerate(cases, start=1):
            identity, raw = self.stage_review_source(
                uid=40 + index, message_id=f'<completed-{tamper}@example.invalid>')
            children = self.batch_payloads(prefix=f'completed-{tamper}')
            bridge.prepare_batch(self.db, identity, hashlib.sha256(raw).hexdigest(), children)
            self.mark_batch_children_delivered(identity)
            bridge.reconcile(self.db)
            self.assertEqual(self.db.execute('SELECT state FROM messages WHERE identity=?',
                                             (identity,)).fetchone()[0], 'delivered')
            with self.db:
                if tamper == 'raw':
                    self.db.execute('UPDATE messages SET raw=? WHERE identity=?',
                                    (raw + b'tampered', identity))
                elif tamper == 'reason':
                    self.db.execute('UPDATE messages SET reason=? WHERE identity=?',
                                    ('message_identity_conflict', identity))
                elif tamper == 'child':
                    self.db.execute('''DELETE FROM mail_preparation_batch_children
                                       WHERE source_identity=? AND delivery_id=?''',
                                    (identity, children[0]['delivery_id']))
                else:
                    self.db.execute('UPDATE receipt_outbox SET receipt_sha256=? WHERE delivery_id=?',
                                    ('0' * 64, children[0]['delivery_id']))
            bridge.reconcile(self.db)
        self.assertEqual(bridge.status(self.db)['batches'], {'blocked': 4})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM messages WHERE state='delivered'").fetchone()[0], 4)

    def test_prepare_batch_rejects_active_caller_transaction(self):
        identity, raw = self.stage_review_source()
        expected = hashlib.sha256(raw).hexdigest()
        with self.db:
            self.db.execute('UPDATE messages SET reason=reason WHERE identity=?', (identity,))
            self.assertTrue(self.db.in_transaction)
            with self.assertRaisesRegex(ValueError, 'batch_transaction_active'):
                bridge.prepare_batch(self.db, identity, expected, self.batch_payloads())
            self.assertTrue(self.db.in_transaction)
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM mail_preparation_batches').fetchone()[0], 0)
            self.db.rollback()

    def test_prepare_batch_serializes_competing_sqlite_connection(self):
        handle, filename = tempfile.mkstemp(prefix='.mail-batch-', suffix='.sqlite3',
                                            dir=os.getcwd())
        os.close(handle)
        first = second = None
        try:
            first = sqlite3.connect(filename, timeout=0.1)
            first.executescript('''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE messages(identity TEXT PRIMARY KEY,uid INTEGER NOT NULL,state TEXT NOT NULL,
                  reason TEXT NOT NULL,payload TEXT NOT NULL,raw BLOB NOT NULL);''')
            mail_stage.set_meta(first, 'uidvalidity', '100')
            first.commit()
            bridge.setup(first)
            msg = message()
            msg.replace_header('Subject', 'Тендер: verified source')
            raw = msg.as_bytes()
            with first:
                mail_stage.stage(first, 1, raw)
            bridge.prepare_pending(first)
            source_identity = first.execute('SELECT identity FROM messages').fetchone()[0]
            second = sqlite3.connect(filename, timeout=0.1)
            bridge.setup(second)
            expected = hashlib.sha256(raw).hexdigest()
            payloads = self.batch_payloads(prefix='serialized')

            first.execute('BEGIN IMMEDIATE')
            first.execute('UPDATE messages SET raw=raw WHERE identity=?', (source_identity,))
            with self.assertRaises(sqlite3.OperationalError):
                bridge.prepare_batch(second, source_identity, expected, payloads)
            self.assertEqual(second.execute('SELECT COUNT(*) FROM receipt_outbox').fetchone()[0], 0)
            first.rollback()

            result = bridge.prepare_batch(second, source_identity, expected, payloads)
            self.assertEqual(result['child_count'], 4)
            self.assertEqual(second.execute('SELECT COUNT(*) FROM receipt_outbox').fetchone()[0], 4)
        finally:
            if second is not None:
                second.close()
            if first is not None:
                first.close()
            os.unlink(filename)


if __name__ == '__main__':
    unittest.main()
