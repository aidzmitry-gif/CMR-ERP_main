import json
import sqlite3
import unittest

import mail_delivery as bridge
import mail_stage
import receipt_queue
from test_mail_receipts import message


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


if __name__ == '__main__':
    unittest.main()
