import base64
import hashlib
import unittest
from email.message import EmailMessage

from mail_receipts import prepare


def message():
    msg = EmailMessage()
    msg['From'] = 'Test Customer <customer@example.invalid>'
    msg['To'] = 'admin@enersys.by'
    msg['Subject'] = 'Запрос аккумуляторов'
    msg['Message-ID'] = '<test-001@example.invalid>'
    msg.set_content('Просим рассчитать аккумуляторы по спецификации.')
    return msg


class MailReceiptTests(unittest.TestCase):
    def test_order_recipient_alone_is_not_site_copy_hold(self):
        for recipient in ('To', 'Cc', 'X-Original-To'):
            for with_file in (False, True):
                msg = message()
                if recipient == 'To':
                    msg.replace_header('To', 'order@microchips.by')
                else:
                    msg[recipient] = 'order@microchips.by'
                if with_file:
                    msg.add_attachment(b'%PDF-1.4 test', maintype='application', subtype='pdf', filename='request.pdf')
                payload, reason = prepare(msg.as_bytes(), 1, 2)
                self.assertIsNone(reason)
                self.assertIsNotNone(payload)
                self.assertEqual(with_file, bool(payload['files']))

    def test_site_sender_provenance_and_boundaries_require_review(self):
        for sender in ('bot@microchips.by', 'bot@forms.microchips.by', 'bot@lpmotor.ru'):
            msg = message()
            msg.replace_header('From', sender)
            self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1],
                             'possible_site_copy_requires_exact_source_id')

        msg = message()
        msg['Sender'] = 'form@microchips.by'
        self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1],
                         'possible_site_copy_requires_exact_source_id')
        for sender in ('bot@notmicrochips.by', 'bot@microchips.by.evil', 'bot@lpmotor.ru.evil'):
            msg = message()
            msg.replace_header('From', sender)
            self.assertIsNone(prepare(msg.as_bytes(), 1, 2)[1])

    def test_mottor_marker_in_html_alternative_requires_review(self):
        msg = message()
        msg.add_alternative('<p>CRM-MOTTOR-20260907</p><input value="mottor:1191119:123">', subtype='html')
        self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1],
                         'possible_site_copy_requires_exact_source_id')

        msg = message()
        msg.set_content('Просим аккумуляторы. form:10:result:2315')
        self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1],
                         'possible_site_copy_requires_exact_source_id')

    def test_rs_markers_require_distinct_form_and_result_names(self):
        msg = message()
        msg.set_content('Просим аккумуляторы. RS_FORM_ID')
        msg.add_alternative('<p>RS_FORM_ID</p>', subtype='html')
        self.assertIsNone(prepare(msg.as_bytes(), 1, 2)[1])

        msg = message()
        msg.set_content('Просим аккумуляторы. rs_form_id и RS_result_id')
        self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1],
                         'possible_site_copy_requires_exact_source_id')

    def test_rs_markers_in_html_are_source_provenance(self):
        msg = message()
        msg.add_alternative(
            '<input name="RS_FORM_ID" value="10"><input name="RS_RESULT_ID" value="2315">',
            subtype='html',
        )
        self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1],
                         'possible_site_copy_requires_exact_source_id')

    def test_omts_sender_is_always_review(self):
        for sender in ('requester@omts.by', 'requester@dept.omts.by'):
            msg = message()
            msg.replace_header('From', sender)
            msg.replace_header('Subject', 'Продажа аккумуляторов')
            msg.add_attachment(b'%PDF-1.4 test', maintype='application', subtype='pdf', filename='request.pdf')
            self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1], 'omts_requires_source_mapping')
        for sender in ('requester@notomts.by', 'requester@omts.by.evil'):
            msg = message()
            msg.replace_header('From', sender)
            self.assertIsNone(prepare(msg.as_bytes(), 1, 2)[1])

    def test_self_mailbox_and_product_link_are_not_site_copy_holds(self):
        msg = message()
        msg.replace_header('From', 'admin@enersys.by')
        self.assertIsNone(prepare(msg.as_bytes(), 1, 2)[1])

        msg = message()
        msg.replace_header('To', 'order@microchips.by')
        msg.set_content('Просим рассчитать аккумуляторы: https://microchips.by/catalog/akb')
        self.assertIsNone(prepare(msg.as_bytes(), 1, 2)[1])

    def test_nested_related_file_is_preserved_with_direct_attachment(self):
        msg = message()
        msg.add_alternative('<p>Просим аккумуляторы</p><img src="cid:spec">', subtype='html')
        msg.get_payload()[1].add_related(b'PNG spec', maintype='image', subtype='png', cid='<spec>', filename='spec.png')
        msg.add_attachment(b'%PDF-1.4 test', maintype='application', subtype='pdf', filename='request.pdf')
        payload, reason = prepare(msg.as_bytes(), 1, 2)
        self.assertIsNone(reason)
        self.assertEqual({f['filename'] for f in payload['files']}, {'spec.png', 'request.pdf'})
        self.assertIn(hashlib.sha256(b'PNG spec').hexdigest(), {f['sha256'] for f in payload['files']})

    def test_procurement_hold_survives_an_attachment(self):
        msg = message()
        msg.replace_header('Subject', 'Тендер: запрос аккумуляторов')
        msg.add_attachment(b'%PDF-1.4 test', maintype='application', subtype='pdf', filename='request.pdf')
        self.assertEqual(prepare(msg.as_bytes(), 1, 2), (None, 'procurement_requires_source_mapping'))

    def test_unsupported_attachment_stays_reviewable(self):
        msg = message()
        msg.add_attachment(b'unsupported', maintype='application', subtype='octet-stream', filename='request.bin')
        self.assertEqual(prepare(msg.as_bytes(), 1, 2), (None, 'attachment_type_requires_review'))

    def test_base64_defect_after_decode_stays_reviewable(self):
        msg = message()
        msg.add_attachment(b'%PDF-1.4 test', maintype='application', subtype='pdf', filename='request.pdf')
        part = msg.get_payload()[-1]
        part.set_payload('JVBERi0xLjQ=***')
        self.assertEqual(prepare(msg.as_bytes(), 1, 2), (None, 'message_decode_defects'))

    def test_customer_attachment_bytes_and_identity_preserved(self):
        msg = message()
        data = b'%PDF-1.4\nTEST ONLY\n'
        msg.add_attachment(data, maintype='application', subtype='pdf', filename='request.pdf')
        payload, reason = prepare(msg.as_bytes(), 1, 2)
        self.assertIsNone(reason)
        file = payload['files'][0]
        self.assertEqual(base64.b64decode(file['data_url'].split(',', 1)[1]), data)
        self.assertEqual(file['sha256'], hashlib.sha256(data).hexdigest())
        self.assertIn('по спецификации', payload['lead']['message'])
        repeated, _ = prepare(msg.as_bytes(), 1, 99)
        self.assertEqual(repeated, payload)

    def test_legacy_doc_attachment_bytes_and_size_are_preserved(self):
        msg = message()
        data = (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + bytes(range(251))) * 200
        data = data[:40960]
        msg.add_attachment(data, maintype='application', subtype='msword', filename='legacy.doc')
        payload, reason = prepare(msg.as_bytes(), 1, 2)
        self.assertIsNone(reason)
        file = payload['files'][0]
        self.assertEqual(file['filename'], 'legacy.doc')
        self.assertEqual(file['size_bytes'], 40960)
        self.assertEqual(file['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(base64.b64decode(file['data_url'].split(',', 1)[1]), data)

    def test_distinct_messages_same_contact_have_distinct_identity(self):
        first = message()
        second = message()
        second.replace_header('Message-ID', '<test-002@example.invalid>')
        self.assertNotEqual(prepare(first.as_bytes(), 1, 2)[0]['source_id'],
                            prepare(second.as_bytes(), 1, 3)[0]['source_id'])

    def test_missing_message_id_uses_mailbox_uid_not_contact(self):
        msg = message()
        del msg['Message-ID']
        self.assertNotEqual(prepare(msg.as_bytes(), 1, 2)[0]['source_id'],
                            prepare(msg.as_bytes(), 1, 3)[0]['source_id'])

    def test_newsletter_and_site_copy_are_not_automatic_leads(self):
        msg = message()
        msg['List-Unsubscribe'] = '<mailto:unsubscribe@example.invalid>'
        msg.add_attachment(b'%PDF-1.4 test', maintype='application', subtype='pdf', filename='request.pdf')
        self.assertEqual(prepare(msg.as_bytes(), 1, 2), (None, 'automatic_or_list_message'))

    def test_legat_billing_does_not_become_a_procurement_lead(self):
        msg = message()
        msg.replace_header('From', 'no-reply@admin.legat.by')
        msg.replace_header('Subject', 'Продажа аккумуляторов')
        msg.add_attachment(b'%PDF-1.4 test', maintype='application', subtype='pdf', filename='request.pdf')
        self.assertEqual(prepare(msg.as_bytes(), 1, 2),
                         (None, 'legat_requires_verified_tender_parser'))
        for sender in ('no-reply@notlegat.by', 'no-reply@legat.by.evil'):
            msg = message()
            msg.replace_header('From', sender)
            self.assertIsNone(prepare(msg.as_bytes(), 1, 2)[1])

    def test_html_only_mail_keeps_readable_request(self):
        msg = message()
        msg.set_content('<p>Просим аккумуляторы</p><script>ignored</script>', subtype='html')
        payload, reason = prepare(msg.as_bytes(), 1, 2)
        self.assertIsNone(reason)
        self.assertEqual(payload['lead']['message'], 'Просим аккумуляторы')

    def test_ambiguous_message_is_review_not_discarded(self):
        msg = message()
        msg.replace_header('Subject', 'Вопрос')
        msg.set_content('Добрый день, вложили документ.')
        self.assertEqual(prepare(msg.as_bytes(), 1, 2), (None, 'customer_intent_requires_review'))

    def test_unsafe_attachment_name_stays_for_review(self):
        msg = message()
        msg.add_attachment(b'test', maintype='text', subtype='plain', filename='../test.txt')
        self.assertEqual(prepare(msg.as_bytes(), 1, 2), (None, 'attachment_filename_requires_review'))


if __name__ == '__main__':
    unittest.main()
