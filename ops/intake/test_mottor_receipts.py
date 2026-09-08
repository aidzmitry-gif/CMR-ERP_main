import datetime as dt
import json
import unittest

import mottor_bridge as source
import mottor_receipts as bridge
import receipt_queue as receipts


class MottorReceipts(unittest.TestCase):
    def setUp(self):
        self.db = source.connect(':memory:')
        receipts.setup(self.db)
        self.now = dt.datetime(2026, 9, 7, 20, tzinfo=dt.timezone.utc)
        source.initialize(self.db, self.now - dt.timedelta(hours=1))
        self.lead = {'id': 123, 'd_created': self.now.isoformat(), 'name': 'test',
                     'page': {'site_id': 1191119, 'site': {'attached_domain': 'enersys.by'}}}
        self.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?)', (123, 'pending', json.dumps(self.lead), self.now.isoformat(), ''))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def result(self, payload):
        return dict(namespace=payload['namespace'], identity_namespace=payload['namespace'],
                    source_id=payload['source_id'], delivery_id=payload['delivery_id'], receipt_id='a'*32,
                    payload_sha256=receipts.receiver_hash(payload), status='delivered', lead_id=1, files=[])

    def test_collection_failure_does_not_block_durable_pending(self):
        result = None
        def fetch(*args):
            raise ConnectionError()
        def post(payload):
            nonlocal result
            result = self.result(payload)
            return result
        self.assertEqual(bridge.cycle(self.db, fetch, post, lambda _: result, self.now), 'ConnectionError')
        self.assertEqual(source.status(self.db), {'delivered': 1})

    def test_legacy_accepted_and_uncertain_not_replayed(self):
        for state in ('accepted', 'sending', 'uncertain'):
            self.db.execute('UPDATE deliveries SET state=?', (state,))
            self.db.commit()
            bridge.stage(self.db)
            self.assertEqual(receipts.status(self.db), {})

    def test_stage_is_atomic_with_source_state_and_idempotent(self):
        bridge.stage(self.db)
        bridge.stage(self.db)
        self.assertEqual(receipts.status(self.db), {'pending': 1})
        self.assertEqual(source.status(self.db), {'v1_pending': 1})
        payload = json.loads(self.db.execute('SELECT payload FROM receipt_outbox').fetchone()[0])
        self.assertEqual(payload['source_id'], 'mottor:1191119:123')
        self.assertIn('[mottor:1191119:123]', payload['lead']['message'])


if __name__ == '__main__':
    unittest.main()
