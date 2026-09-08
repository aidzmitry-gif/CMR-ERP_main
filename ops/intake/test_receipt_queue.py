import copy
import json
import sqlite3
import unittest
from pathlib import Path

import receipt_queue as q


class Receipts(unittest.TestCase):
    def test_actual_receiver_golden_contract(self):
        fixtures = json.loads(Path(__file__).with_name('receipt-contract-golden.json').read_text(encoding='utf-8-sig'))
        for item in fixtures:
            self.assertEqual(q.receiver_hash(item['request']), item['receiver_sha256'])

    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        q.setup(self.db)
        self.payload = {'namespace': 'enersys.by', 'source_id': 'mottor:1191119:123',
                        'delivery_id': 'mottor:1191119:123', 'lead': {'message': 'test'}}
        with self.db:
            q.enqueue(self.db, self.payload)
        self.receipt = dict(namespace='enersys.by', identity_namespace='enersys.by',
                            source_id=self.payload['source_id'], delivery_id=self.payload['delivery_id'],
                            receipt_id='a' * 32, payload_sha256=q.receiver_hash(self.payload),
                            status='delivered', lead_id=42, files=[])

    def tearDown(self):
        self.db.close()

    def test_post_ack_is_not_delivery(self):
        queued = dict(self.receipt, status='queued', lead_id=None)
        self.assertEqual(q.deliver(self.db, lambda _: self.receipt, lambda _: queued), 0)
        self.assertEqual(q.status(self.db), {'queued': 1})

    def test_exact_replay_after_lost_response(self):
        sent = []
        def lost(payload):
            sent.append(payload)
            raise TimeoutError()
        self.assertEqual(q.deliver(self.db, lost, lambda _: self.receipt), 0)
        def retry(payload):
            sent.append(payload)
            return self.receipt
        self.assertEqual(q.deliver(self.db, retry, lambda _: self.receipt), 1)
        self.assertEqual(sent[0], sent[1])
        self.assertEqual(q.deliver(self.db, retry, lambda _: self.receipt), 0)
        self.assertEqual(len(sent), 2)

    def test_altered_delivery_rejected_before_send(self):
        changed = copy.deepcopy(self.payload)
        changed['lead']['message'] = 'other request'
        with self.assertRaisesRegex(ValueError, 'immutable_delivery_conflict'):
            q.enqueue(self.db, changed)

    def test_receipt_identity_mismatch(self):
        wrong = dict(self.receipt, source_id='other')
        self.assertEqual(q.deliver(self.db, lambda _: wrong, lambda _: wrong), 0)
        self.assertEqual(q.status(self.db), {'retry': 1})

    def test_get_hash_must_equal_post(self):
        changed = dict(self.receipt, payload_sha256='c' * 64)
        self.assertEqual(q.deliver(self.db, lambda _: self.receipt, lambda _: changed), 0)

    def test_no_lead_id_is_not_delivery(self):
        wrong = dict(self.receipt, lead_id=None)
        self.assertEqual(q.deliver(self.db, lambda _: wrong, lambda _: wrong), 0)

    def test_process_restart_sending_replays(self):
        self.db.execute("UPDATE receipt_outbox SET state='sending'")
        self.db.commit()
        self.assertEqual(q.deliver(self.db, lambda _: self.receipt, lambda _: self.receipt), 1)

    def test_corrupted_local_payload_never_sends(self):
        self.db.execute("UPDATE receipt_outbox SET payload='{}'")
        self.db.commit()
        def forbidden(_):
            self.fail('corrupted data sent')
        q.deliver(self.db, forbidden, forbidden)
        self.assertEqual(self.db.execute('SELECT last_error FROM receipt_outbox').fetchone()[0], 'local_payload_corrupted')

    def test_file_bytes_and_attachment_id_required(self):
        payload = copy.deepcopy(self.payload)
        payload['files'] = [{'file_id': '1', 'filename': 'quote.pdf', 'size_bytes': 5, 'sha256': 'c' * 64, 'data_url': 'data:application/pdf;base64,dGVzdA=='}]
        receipt = dict(self.receipt, payload_sha256=q.receiver_hash(payload), files=[dict(payload['files'][0], attachment_id=12)])
        q.validate_receipt(receipt, payload)
        for key, value in [('sha256', 'd' * 64), ('size_bytes', 4), ('attachment_id', None)]:
            changed = copy.deepcopy(receipt)
            changed['files'][0][key] = value
            with self.assertRaises(ValueError):
                q.validate_receipt(changed, payload)

    def test_failed_receipt_retries_and_confirms(self):
        failed = dict(self.receipt, status='failed', lead_id=None)
        self.assertEqual(q.deliver(self.db, lambda _: failed, lambda _: failed), 0)
        self.assertEqual(q.status(self.db), {'failed': 1})
        self.assertEqual(q.deliver(self.db, lambda _: self.receipt, lambda _: self.receipt), 1)


if __name__ == '__main__':
    unittest.main()
