import base64
import hashlib
import io
import unittest
import warnings
import zipfile
from email.message import EmailMessage
from xml.sax.saxutils import escape

from mail_receipts import DOCX_MIME, prepare


def message():
    msg = EmailMessage()
    msg['From'] = 'Test Customer <customer@example.invalid>'
    msg['To'] = 'admin@enersys.by'
    msg['Subject'] = 'Запрос аккумуляторов'
    msg['Message-ID'] = '<test-001@example.invalid>'
    msg.set_content('Просим рассчитать аккумуляторы по спецификации.')
    return msg


def docx_bytes(paragraphs, raw_xml=None, *, duplicate=False, extra_entries=0,
               compression=zipfile.ZIP_DEFLATED, encrypted=False):
    namespace = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    if raw_xml is None:
        xml_paragraphs = []
        for paragraph in paragraphs:
            runs = paragraph if isinstance(paragraph, (list, tuple)) else [paragraph]
            xml_paragraphs.append('<w:p>' + ''.join(f'<w:r><w:t>{escape(run)}</w:t></w:r>' for run in runs) + '</w:p>')
        raw_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<w:document xmlns:w="{namespace}"><w:body>{"".join(xml_paragraphs)}</w:body></w:document>'
        ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        info = zipfile.ZipInfo('word/document.xml')
        info.compress_type = compression
        if encrypted:
            info.flag_bits |= 0x1
        archive.writestr(info, raw_xml)
        if duplicate:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                archive.writestr('word/document.xml', raw_xml)
        for index in range(extra_entries):
            archive.writestr(f'extra/{index}.bin', b'x')
    result = bytearray(output.getvalue())
    if encrypted:
        offset = 0
        while True:
            offset = result.find(b'PK\x03\x04', offset)
            if offset < 0:
                break
            result[offset + 6] |= 0x01
            offset += 4
        offset = 0
        while True:
            offset = result.find(b'PK\x01\x02', offset)
            if offset < 0:
                break
            result[offset + 8] |= 0x01
            offset += 4
    return bytes(result)


def add_docx(msg, data, filename='request.docx'):
    msg.add_attachment(data, maintype='application', subtype=DOCX_MIME.split('/', 1)[1], filename=filename)


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

    def test_consultation_cue_requires_battery_product(self):
        msg = message()
        msg.replace_header('Subject', 'Вопрос по совместимости')
        msg.set_content('Подскажите, пожалуйста, подойдёт ли аккумулятор к этой модели?')
        payload, reason = prepare(msg.as_bytes(), 1, 2)
        self.assertIsNone(reason)
        self.assertIsNotNone(payload)

        msg = message()
        msg.replace_header('Subject', 'Вопрос')
        msg.set_content('Подскажите, пожалуйста, по срокам поставки.')
        self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1], 'customer_intent_requires_review')

    def test_docx_request_is_intent_evidence_only_and_bytes_are_preserved(self):
        for paragraphs in (
            [['Просим предоставить ', 'КП на аккумуляторы.']],
            ['Подскажите, пожалуйста, совместимость батареи с погрузчиком.'],
        ):
            msg = message()
            msg.replace_header('Subject', 'Документы')
            msg.set_content('С уважением,\nКлиент')
            data = docx_bytes(paragraphs)
            add_docx(msg, data)
            payload, reason = prepare(msg.as_bytes(), 1, 2)
            self.assertIsNone(reason)
            self.assertEqual(payload['lead']['message'], 'С уважением,\nКлиент\n')
            file = payload['files'][0]
            self.assertEqual(file['filename'], 'request.docx')
            self.assertEqual(file['size_bytes'], len(data))
            self.assertEqual(file['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(base64.b64decode(file['data_url'].split(',', 1)[1]), data)

    def test_docx_and_inline_files_remain_distinct(self):
        msg = message()
        msg.replace_header('Subject', 'Документы')
        msg.set_content('С уважением,\nКлиент')
        docx = docx_bytes(['Просим предоставить КП на аккумуляторы.'])
        add_docx(msg, docx)
        msg.add_attachment(b'PNG bytes', maintype='image', subtype='png', filename='photo.png')
        payload, reason = prepare(msg.as_bytes(), 1, 2)
        self.assertIsNone(reason)
        self.assertEqual({file['filename'] for file in payload['files']}, {'request.docx', 'photo.png'})
        self.assertEqual(
            {file['sha256'] for file in payload['files']},
            {hashlib.sha256(docx).hexdigest(), hashlib.sha256(b'PNG bytes').hexdigest()},
        )

    def test_docx_negative_source_and_procurement_markers_survive_intent_fallback(self):
        msg = message()
        msg.replace_header('Subject', 'Документы')
        msg.set_content('С уважением')
        add_docx(msg, docx_bytes(['Просим аккумуляторы. form:10:result:2315']))
        self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1], 'possible_site_copy_requires_exact_source_id')

        msg = message()
        msg.replace_header('Subject', 'Документы')
        msg.set_content('С уважением')
        add_docx(msg, docx_bytes(['Просим подготовить документы для тендера аккумуляторов.']))
        self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1], 'procurement_requires_source_mapping')

        msg = message()
        msg.replace_header('Subject', 'О поставке')
        msg.set_content('С уважением')
        add_docx(msg, docx_bytes(['Коммерческое предложение по логистике.']))
        self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1], 'customer_intent_requires_review')

    def test_docx_repeat_is_deterministic_for_same_message_id(self):
        msg = message()
        msg.replace_header('Subject', 'Документы')
        msg.set_content('С уважением')
        add_docx(msg, docx_bytes(['Просим предоставить КП на аккумуляторы.']))
        first, first_reason = prepare(msg.as_bytes(), 1, 2)
        repeated, repeated_reason = prepare(msg.as_bytes(), 1, 99)
        self.assertIsNone(first_reason)
        self.assertIsNone(repeated_reason)
        self.assertEqual(repeated, first)

    def test_docx_malformed_archive_or_xml_is_explicit_review(self):
        cases = (
            (b'not a zip', 'docx_archive_requires_review'),
            (docx_bytes([], raw_xml=b'<x:document xmlns:x="urn:unknown"><x:body/></x:document>'), 'docx_namespace_requires_review'),
            (docx_bytes([], raw_xml=b'<!DOCTYPE document><w:document/>'), 'docx_xml_requires_review'),
            (docx_bytes([], raw_xml=b'<?xml version="1.0" encoding = "UTF-16"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'), 'docx_utf8_requires_review'),
            (docx_bytes(['Просим аккумуляторы.'], duplicate=True), 'docx_document_xml_requires_review'),
            (docx_bytes(['Просим аккумуляторы.'], extra_entries=128), 'docx_archive_limits_require_review'),
        )
        for data, expected_reason in cases:
            msg = message()
            msg.replace_header('Subject', 'Документы')
            msg.set_content('С уважением')
            add_docx(msg, data)
            self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1], expected_reason)

    def test_docx_nested_paragraph_is_bounded_review(self):
        namespace = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        nested = '<w:p>' * 500 + '<w:r><w:t>' + ('x' * 5000) + '</w:t></w:r>' + '</w:p>' * 500
        raw_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<w:document xmlns:w="{namespace}"><w:body>{nested}</w:body></w:document>'
        ).encode()
        msg = message()
        msg.replace_header('Subject', 'Документы')
        msg.set_content('С уважением')
        add_docx(msg, docx_bytes([], raw_xml=raw_xml))
        self.assertEqual(
            prepare(msg.as_bytes(), 1, 2)[1],
            'docx_nested_paragraph_requires_review',
        )

    def test_docx_encryption_compression_and_text_limits_are_review(self):
        encrypted = docx_bytes(['Просим аккумуляторы.'], encrypted=True)
        msg = message()
        msg.replace_header('Subject', 'Документы')
        msg.set_content('С уважением')
        add_docx(msg, encrypted)
        self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1], 'docx_encrypted_requires_review')

        if hasattr(zipfile, 'ZIP_BZIP2'):
            compressed = docx_bytes(['Просим аккумуляторы.'], compression=zipfile.ZIP_BZIP2)
            msg = message()
            msg.replace_header('Subject', 'Документы')
            msg.set_content('С уважением')
            add_docx(msg, compressed)
            self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1], 'docx_compression_requires_review')

        oversized = docx_bytes(['Просим аккумуляторы. ' + ('x' * (64 * 1024))])
        msg = message()
        msg.replace_header('Subject', 'Документы')
        msg.set_content('С уважением')
        add_docx(msg, oversized)
        self.assertEqual(prepare(msg.as_bytes(), 1, 2)[1], 'docx_text_limits_require_review')

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
