import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import Mock

from mail_stage import get_meta, initialize, open_queue, parse_message, poll, stage


def message(mid='one', extra='', text='Просим цену на аккумуляторы', subject='Запрос'):
    return (f'From: buyer@example.invalid\r\nTo: admin@enersys.by\r\n'
            f'Message-ID: <{mid}@example.invalid>\r\nSubject: {subject}\r\n'
            f'Content-Type: text/plain; charset=utf-8\r\n{extra}\r\n{text}').encode()


def client(next_uid=11, validity=1):
    c = Mock()
    c.select.return_value = ('OK', [b'10'])
    c.response.side_effect = lambda k: (k, [str(validity if k == 'UIDVALIDITY' else next_uid).encode()])
    return c


class MailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = open_queue(Path(self.temp.name) / 'queue.sqlite3')

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_candidate_is_not_automatically_sent(self):
        self.assertEqual(parse_message(message())[1:3], ('candidate', 'customer_request_candidate'))

    def test_lists_and_automated_messages_stay_for_review(self):
        for extra in ('List-ID: <newsletter.example.invalid>\r\n', 'Auto-Submitted: auto-replied\r\n'):
            self.assertEqual(parse_message(message(extra=extra))[1:3],
                             ('review', 'automatic_or_list_message'))

    def test_site_copy_requires_reconciliation(self):
        raw = message(extra='X-Original-To: order@microchips.by\r\n')
        self.assertEqual(parse_message(raw)[2], 'possible_site_copy')

    def test_attachment_request_is_preserved_for_processing(self):
        msg = EmailMessage()
        msg['From'] = 'buyer@example.invalid'
        msg['To'] = 'admin@enersys.by'
        msg['Subject'] = 'Запрос аккумуляторов'
        msg.set_content('Просим цену на аккумулятор, спецификация во вложении')
        msg.add_attachment(b'synthetic specification', maintype='application',
                           subtype='octet-stream', filename='specification.txt')
        raw = msg.as_bytes()
        stage(self.db, 1, raw)
        state, reason, stored = self.db.execute('SELECT state, reason, raw FROM messages').fetchone()
        self.assertEqual((state, reason), ('review', 'attachments_require_processing'))
        self.assertEqual(stored, raw)

    def test_html_only_message_remains_reviewable(self):
        raw = message().replace(b'text/plain', b'text/html')
        self.assertEqual(parse_message(raw)[1], 'review')

    def test_same_sender_different_requests_are_preserved(self):
        stage(self.db, 1, message('one'))
        stage(self.db, 2, message('one'))
        stage(self.db, 3, message('two'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 2)

    def test_missing_id_uses_stable_content_hash(self):
        raw = message().replace(b'Message-ID: <one@example.invalid>\r\n', b'')
        self.assertEqual(parse_message(raw)[0], parse_message(raw)[0])
        self.assertTrue(parse_message(raw)[0].startswith('sha256:'))

    def test_missing_id_staging_preserves_distinct_uids(self):
        raw = message().replace(b'Message-ID: <one@example.invalid>\r\n', b'')
        initialize(self.db, client())
        stage(self.db, 11, raw)
        stage(self.db, 12, raw)
        stage(self.db, 12, raw)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 2)

    def test_reused_message_id_keeps_changed_content_for_review(self):
        stage(self.db, 1, message())
        changed = message(text='Просим другие аккумуляторы')
        stage(self.db, 2, changed)
        stage(self.db, 2, changed)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 2)
        row = self.db.execute("SELECT reason,raw FROM messages WHERE state='review'").fetchone()
        self.assertEqual(row, ('message_identity_conflict', changed))

    def test_init_sets_new_mail_boundary_without_fetching_history(self):
        c = client()
        initialize(self.db, c)
        self.assertEqual(get_meta(self.db, 'last_uid'), '10')
        c.select.assert_called_once_with('INBOX', readonly=True)
        c.uid.assert_not_called()
        with self.assertRaises(RuntimeError):
            initialize(self.db, c)

    def test_no_new_mail_does_not_search_backwards(self):
        c = client()
        initialize(self.db, c)
        self.assertEqual(poll(self.db, c), {'fetched': 0})
        c.uid.assert_not_called()

    def test_uidvalidity_change_stops_without_advancing(self):
        initialize(self.db, client())
        with self.assertRaisesRegex(RuntimeError, 'uidvalidity_changed'):
            poll(self.db, client(validity=2))
        self.assertEqual(get_meta(self.db, 'last_uid'), '10')

    def test_fetch_is_read_only_and_restart_does_not_duplicate(self):
        initialize(self.db, client())
        c = client(next_uid=12)
        raw = message()
        c.uid.side_effect = [('OK', [b'11']), ('OK', [b'1 (RFC822.SIZE 100)']),
                             ('OK', [(b'1 BODY[]', raw), b')'])]
        self.assertEqual(poll(self.db, c), {'fetched': 1})
        self.assertIn(('fetch', '11', '(BODY.PEEK[])'), [x.args for x in c.uid.call_args_list])
        self.assertEqual(get_meta(self.db, 'last_uid'), '11')
        self.assertEqual(poll(self.db, client(next_uid=12)), {'fetched': 0})
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 1)

    def test_fetch_failure_preserves_watermark_for_retry(self):
        initialize(self.db, client())
        c = client(next_uid=12)
        c.uid.side_effect = [('OK', [b'11']), ('NO', [b'failure'])]
        with self.assertRaises(RuntimeError):
            poll(self.db, c)
        self.assertEqual(get_meta(self.db, 'last_uid'), '10')

    def test_oversize_is_visible_and_not_downloaded(self):
        initialize(self.db, client())
        c = client(next_uid=12)
        c.uid.side_effect = [('OK', [b'11']), ('OK', [b'1 (RFC822.SIZE 33554433)'])]
        poll(self.db, c)
        self.assertEqual(c.uid.call_count, 2)
        self.assertEqual(self.db.execute('SELECT reason FROM messages').fetchone()[0],
                         'oversized_original_in_mailbox')


if __name__ == '__main__':
    unittest.main()
