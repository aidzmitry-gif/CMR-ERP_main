import datetime as dt
import unittest
from unittest.mock import Mock

from mottor_bridge import collect, connect, deliver, initialize, meta, status

START = dt.datetime(2026, 9, 7, 20, tzinfo=dt.timezone.utc)
NOW = START + dt.timedelta(minutes=1)


def lead(id=1, **extra):
    result = {'id': id, 'page': {'site_id': 1191119, 'site': {'attached_domain': 'enersys.by'}},
              'd_created': NOW.isoformat(), 'name': 'TEST', 'email': 'test@example.invalid',
              'history': [{'message': 'Нужна батарея'}], 'cart': None, 'is_del': 0}
    result.update(extra)
    return result


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.db = connect(':memory:')
        initialize(self.db, START)

    def tearDown(self):
        self.db.close()

    def test_new_boundary_and_empty_poll(self):
        fetch = Mock(return_value={'count': 0, 'leads': []})
        collect(self.db, fetch, NOW)
        self.assertEqual(fetch.call_args.args[1]['d_create_start'], START.isoformat())
        self.assertEqual(meta(self.db, 'cursor'), NOW.isoformat())
        with self.assertRaises(ValueError):
            initialize(self.db, NOW)

    def test_full_payload_retained_and_repeat_sent_once(self):
        row = lead()
        fetch = Mock(side_effect=[{'count': 1, 'leads': [row]}, row])
        collect(self.db, fetch, NOW)
        send = Mock(return_value={'ok': True, 'source': 'site'})
        deliver(self.db, send)
        collect(self.db, Mock(return_value={'count': 1, 'leads': [row]}), NOW)
        deliver(self.db, send)
        send.assert_called_once()
        self.assertIn('Нужна батарея', send.call_args.args[0]['message'])
        self.assertIn('[mottor:1191119:1]', send.call_args.args[0]['message'])

    def test_distinct_requests_same_sender_are_both_delivered(self):
        rows = [lead(1), lead(2)]
        collect(self.db, Mock(side_effect=[{'count': 2, 'leads': rows}, *rows]), NOW)
        send = Mock(return_value={'ok': True, 'source': 'site'})
        deliver(self.db, send)
        self.assertEqual(send.call_count, 2)

    def test_uncertain_post_is_never_blindly_retried(self):
        collect(self.db, Mock(side_effect=[{'count': 1, 'leads': [lead()]}, lead()]), NOW)
        send = Mock(side_effect=TimeoutError)
        deliver(self.db, send)
        deliver(self.db, send)
        send.assert_called_once()
        self.assertEqual(status(self.db), {'uncertain': 1})

    def test_failure_during_fetch_keeps_cursor_and_preserves_first_row(self):
        collect_mock = Mock(side_effect=[{'count': 2, 'leads': [lead(1), lead(2)]}, lead(1), TimeoutError])
        with self.assertRaises(TimeoutError):
            collect(self.db, collect_mock, NOW)
        self.assertEqual(meta(self.db, 'cursor'), START.isoformat())
        self.assertEqual(status(self.db), {'pending': 1})

    def test_wrong_site_and_ignored_date_filter_stop(self):
        for row in [lead(page={'site_id': 5}), lead(d_created=(START-dt.timedelta(days=1)).isoformat())]:
            with self.assertRaises(ValueError):
                collect(self.db, Mock(return_value={'count': 1, 'leads': [row]}), NOW)
            self.assertEqual(meta(self.db, 'cursor'), START.isoformat())

    def test_no_contact_request_is_delivered_with_source_document(self):
        row = lead(email='')
        collect(self.db, Mock(side_effect=[{'count': 1, 'leads': [row]}, row]), NOW)
        send = Mock(return_value={'ok': True, 'source': 'site'})
        deliver(self.db, send)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0]['email'], '')
        self.assertIn('[mottor:1191119:1]', send.call_args.args[0]['message'])
        self.assertIn('Нужна батарея', send.call_args.args[0]['message'])
        self.assertEqual(status(self.db), {'accepted': 1})

    def test_late_source_visibility_is_reconciled_after_cursor_moves(self):
        later = START + dt.timedelta(hours=3)
        collect(self.db, Mock(return_value={'count': 0, 'leads': []}), later)
        fetch = Mock(side_effect=[{'count': 1, 'leads': [lead()]}, lead()])
        self.assertEqual(collect(self.db, fetch, later + dt.timedelta(minutes=2)), 1)
        self.assertEqual(fetch.call_args_list[0].args[1]['d_create_start'], START.isoformat())
        self.assertEqual(status(self.db), {'pending': 1})

    def test_duplicate_or_reordered_source_page_does_not_advance_cursor(self):
        for rows in ([lead(2), lead(1)], [lead(2), lead(2)]):
            fetch = Mock(side_effect=[{'count': 2, 'leads': rows}, lead(2)])
            with self.assertRaisesRegex(ValueError, 'strictly_increasing'):
                collect(self.db, fetch, NOW)
            self.assertEqual(meta(self.db, 'cursor'), START.isoformat())

    def test_crash_after_send_claim_does_not_resend(self):
        row = lead()
        collect(self.db, Mock(side_effect=[{'count': 1, 'leads': [row]}, row]), NOW)
        self.db.execute("UPDATE deliveries SET state='sending'")
        self.db.commit()
        send = Mock()
        deliver(self.db, send)
        send.assert_not_called()
        self.assertEqual(status(self.db), {'sending': 1})

    def test_incomplete_pagination_does_not_advance(self):
        with self.assertRaises(ValueError):
            collect(self.db, Mock(return_value={'count': 10, 'leads': []}), NOW)
        self.assertEqual(meta(self.db, 'cursor'), START.isoformat())


if __name__ == '__main__':
    unittest.main()
