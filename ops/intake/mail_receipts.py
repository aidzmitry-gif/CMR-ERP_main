"""Prepare a new-intake request from a staged message; no network or mail writes.

Ambiguous mail remains reviewable with its original MIME. Never infer a site or
tender identity from an address alone. This module does not declare delivery.
"""
import base64
import hashlib
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser

MAILBOX = 'admin@enersys.by'
DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
DOCX_MAX_ENTRIES = 128
DOCX_MAX_XML_BYTES = 256 * 1024
DOCX_MAX_TEXT_BYTES = 64 * 1024
DOCX_WORD_NAMESPACES = frozenset({
    'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'http://purl.oclc.org/ooxml/wordprocessingml/main',
})
FILE_TYPES = {
    'application/pdf': '.pdf',
    'application/msword': '.doc',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
    DOCX_MIME: '.docx',
    'image/jpeg': '.jpg', 'image/png': '.png',
}
SITE_COPY_MARKER_RE = re.compile(
    r'\b(?:form:\d+:result:\d+|mottor:[A-Za-z0-9._-]+:[A-Za-z0-9._-]+)\b', re.IGNORECASE
)
RS_FORM_MARKER_RE = re.compile(r'\bRS_FORM_ID\b', re.IGNORECASE)
RS_RESULT_MARKER_RE = re.compile(r'\bRS_RESULT_ID\b', re.IGNORECASE)
_REQUEST_FOR_PROCUREMENT_RE = (
    r'(?:заявка|заявку|заявки|заявке|заявкой|заявок|заявкам|заявками|заявках)'
    r'\s+на\s+'
    r'(?:закупка|закупку|закупки|закупке|закупкой|закупок|закупкам|закупками|закупках)'
)
_AGENT_FOR_PROCUREMENT_RE = (
    r'(?:агент|агента|агенту|агентом|агенте|агенты|агентов|агентам|агентами|агентах)'
    r'\s+по\s+'
    r'(?:закупка|закупку|закупки|закупке|закупкой|закупок|закупкам|закупками|закупках)'
)
DIRECT_CUSTOMER_PROCUREMENT_RE = re.compile(
    rf'\b(?:{_REQUEST_FOR_PROCUREMENT_RE}|{_AGENT_FOR_PROCUREMENT_RE})\b',
    re.IGNORECASE,
)
_PROCUREMENT_ID_SEPARATOR_RE = r'[\s:;,./()\-–—]*'
DIRECT_CUSTOMER_PROCUREMENT_ID_RE = re.compile(
    rf'\b(?:{_REQUEST_FOR_PROCUREMENT_RE}|{_AGENT_FOR_PROCUREMENT_RE})\b'
    rf'{_PROCUREMENT_ID_SEPARATOR_RE}'
    r'(?:(?:№|#)\s*[0-9A-Za-zА-Яа-яЁё]+(?:[/-][0-9A-Za-zА-Яа-яЁё]+)*'
    r'|(?:n|no\.?|номер)\s*(?=[0-9])[0-9A-Za-zА-Яа-яЁё]+(?:[/-][0-9A-Za-zА-Яа-яЁё]+)*'
    r'|[0-9]+(?:[/-][0-9A-Za-zА-Яа-яЁё]+)*)',
    re.IGNORECASE,
)
HARD_PROCUREMENT_RE = re.compile(
    r'\b(?:тендер\w*|лот|лота|лоту|лоте|лотом|лоты|лотов|лотам|лотами|лотах|'
    r'lot|lots|приглаш\w*|invitation)\b'
    r'|\bмаркетинговое\s+исследование\b',
    re.IGNORECASE,
)


class MailText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif not self.hidden and tag in ('br', 'p', 'div', 'tr', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _domain_matches(domain, base):
    domain = domain.rstrip('.').casefold()
    base = base.rstrip('.').casefold()
    return domain == base or domain.endswith('.' + base)


def _sender_domains(msg):
    values = []
    for header in ('From', 'Sender'):
        values.extend(str(value) for value in msg.get_all(header, []))
    return [address.rsplit('@', 1)[1].casefold().rstrip('.')
            for _, address in getaddresses(values) if '@' in address]


def _text_parts_for_markers(msg):
    parts = []
    for part in msg.walk():
        if (part.is_multipart() or part.get_content_disposition() == 'attachment'
                or part.get_content_type() not in ('text/plain', 'text/html')):
            continue
        data = part.get_payload(decode=True)
        if not isinstance(data, bytes):
            continue
        charset = part.get_content_charset() or 'utf-8'
        try:
            parts.append(data.decode(charset, errors='ignore'))
        except (LookupError, UnicodeError):
            parts.append(data.decode('utf-8', errors='ignore'))
    return parts


def _has_site_copy_provenance(msg, subject):
    domains = _sender_domains(msg)
    if any(_domain_matches(domain, base) for domain in domains for base in ('microchips.by', 'lpmotor.ru')):
        return True
    searchable = '\n'.join([subject, *_text_parts_for_markers(msg)])
    if SITE_COPY_MARKER_RE.search(searchable):
        return True
    return bool(RS_FORM_MARKER_RE.search(searchable) and RS_RESULT_MARKER_RE.search(searchable))


def _has_site_copy_text_provenance(text):
    return bool(SITE_COPY_MARKER_RE.search(text)
                or (RS_FORM_MARKER_RE.search(text) and RS_RESULT_MARKER_RE.search(text)))


def _has_procurement_language(text):
    combined = text.casefold()
    if DIRECT_CUSTOMER_PROCUREMENT_ID_RE.search(combined):
        return True
    residual = DIRECT_CUSTOMER_PROCUREMENT_RE.sub(' ', combined)
    return bool(HARD_PROCUREMENT_RE.search(residual) or 'закупк' in residual)


def _has_customer_intent(subject, text):
    combined = (subject + '\n' + text).casefold()
    return (any(x in combined for x in (
        'прошу', 'просим', 'нужен', 'нужны', 'запрос', 'заявка', 'подскажите'))
        and any(x in combined for x in (
            'аккумулятор', 'батаре', 'элемент питан', 'акб',
            'источник бесперебойного питания')))


def _extract_docx_intent_text(data):
    """Read bounded Word text in memory for intent evidence only."""
    try:
        with zipfile.ZipFile(io.BytesIO(data), 'r') as archive:
            infos = archive.infolist()
            if len(infos) > DOCX_MAX_ENTRIES:
                return None, 'docx_archive_limits_require_review'
            if any(info.flag_bits & 0x1 for info in infos):
                return None, 'docx_encrypted_requires_review'
            if any(info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                   for info in infos):
                return None, 'docx_compression_requires_review'
            documents = [info for info in infos if info.filename == 'word/document.xml']
            if len(documents) != 1 or documents[0].is_dir():
                return None, 'docx_document_xml_requires_review'
            document = documents[0]
            if document.file_size < 0 or document.file_size > DOCX_MAX_XML_BYTES:
                return None, 'docx_xml_limits_require_review'
            with archive.open(document, 'r') as stream:
                xml_data = stream.read(DOCX_MAX_XML_BYTES + 1)
            if len(xml_data) > DOCX_MAX_XML_BYTES:
                return None, 'docx_xml_limits_require_review'
    except (zipfile.BadZipFile, EOFError, NotImplementedError, OSError, RuntimeError, ValueError):
        return None, 'docx_archive_requires_review'

    if b'\x00' in xml_data or re.search(rb'<!DOCTYPE\b|<!ENTITY\b', xml_data, re.IGNORECASE):
        return None, 'docx_xml_requires_review'
    try:
        xml_text = xml_data.decode('utf-8-sig', errors='strict')
    except UnicodeDecodeError:
        return None, 'docx_utf8_requires_review'
    declaration = re.match(
        r'\s*<\?xml[^>]*encoding\s*=\s*["\']([^"\']+)',
        xml_text,
        re.IGNORECASE,
    )
    if declaration and declaration.group(1).casefold().replace('-', '') != 'utf8':
        return None, 'docx_utf8_requires_review'
    try:
        parser = ET.iterparse(io.StringIO(xml_text), events=('start', 'end'))
        paragraph_tag = text_tag = None
        seen_root = False
        paragraph_parts = None
        paragraphs = []
        text_bytes = 0
        for event, element in parser:
            if event == 'start':
                if not seen_root:
                    seen_root = True
                    if not isinstance(element.tag, str) or not element.tag.startswith('{'):
                        return None, 'docx_namespace_requires_review'
                    namespace, local_name = element.tag[1:].split('}', 1)
                    if namespace not in DOCX_WORD_NAMESPACES or local_name != 'document':
                        return None, 'docx_namespace_requires_review'
                    paragraph_tag = '{' + namespace + '}p'
                    text_tag = '{' + namespace + '}t'
                elif element.tag == paragraph_tag:
                    if paragraph_parts is not None:
                        return None, 'docx_nested_paragraph_requires_review'
                    paragraph_parts = []
            elif element.tag == text_tag and paragraph_parts is not None:
                paragraph_parts.append(element.text or '')
            elif element.tag == paragraph_tag and paragraph_parts is not None:
                paragraph = ''.join(paragraph_parts)
                if paragraphs:
                    text_bytes += 1
                text_bytes += len(paragraph.encode('utf-8'))
                if text_bytes > DOCX_MAX_TEXT_BYTES:
                    return None, 'docx_text_limits_require_review'
                paragraphs.append(paragraph)
                paragraph_parts = None
            if event == 'end':
                element.clear()
    except ET.ParseError:
        return None, 'docx_xml_requires_review'
    text = '\n'.join(paragraphs).strip()
    return text, None


def prepare(raw, uidvalidity, uid):
    """Return (request, None), or (None, explicit review/exclusion reason).

    Selection is deliberately conservative until real-mail acceptance: a review
    reason is not an assertion that a message is irrelevant.
    """
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    if any(part.defects for part in msg.walk()):
        return None, 'message_parse_defects'
    name, address = parseaddr(str(msg.get('From', '')))
    if not address or '@' not in address:
        return None, 'sender_requires_review'
    sender_domains = _sender_domains(msg)
    if any(_domain_matches(value, 'omts.by') for value in sender_domains):
        return None, 'omts_requires_source_mapping'
    # A separate parser must verify the actual tender/lot/template, rather than
    # importing Legat billing and account administration as customer requests.
    if any(_domain_matches(value, 'legat.by') for value in sender_domains):
        return None, 'legat_requires_verified_tender_parser'
    if (msg.get('List-ID') or msg.get('List-Unsubscribe') or
            str(msg.get('Precedence', '')).casefold() in ('bulk', 'list') or
            str(msg.get('Auto-Submitted', 'no')).casefold() != 'no'):
        return None, 'automatic_or_list_message'
    body = msg.get_body(preferencelist=('plain', 'html'))
    try:
        text = (body.get_payload(decode=True) or b'').decode(body.get_content_charset() or 'ascii') if body else ''
    except (LookupError, UnicodeError):
        return None, 'body_decode_requires_review'
    if body and body.defects:
        return None, 'message_decode_defects'
    if body and body.get_content_type() == 'text/html':
        parser = MailText()
        parser.feed(text)
        text = ''.join(parser.parts).strip()
    subject = str(msg.get('Subject', ''))
    if _has_site_copy_provenance(msg, subject):
        return None, 'possible_site_copy_requires_exact_source_id'
    if _has_procurement_language(subject + '\n' + text):
        return None, 'procurement_requires_source_mapping'
    text_intent = _has_customer_intent(subject, text)
    message_id = str(msg.get('Message-ID', '')).strip()
    if (len(message_id) > 998 or len(subject) > 4096 or len(text.encode()) > 256 * 1024
            or len(name) > 255 or len(address) > 128 or '\x00' in name + address + subject + text):
        return None, 'message_exceeds_receiver_limits'
    identity = message_id or f'{MAILBOX}:{uidvalidity}:{uid}'
    key = 'mail:' + hashlib.sha256(identity.encode()).hexdigest()
    files = []
    # walk() includes inline files nested under multipart/related. Direct-only
    # iter_attachments() silently omitted those files from a delivered receipt.
    docx_parts = []
    for part_number, part in enumerate(msg.walk(), 1):
        if part.get_content_type() == 'message/rfc822':
            return None, 'attached_message_requires_review'
        if part.is_multipart() or part is body:
            continue
        is_file = (part.get_content_disposition() == 'attachment' or part.get_filename()
                   or part.get('Content-ID') or part.get_content_type() not in ('text/plain', 'text/html'))
        if not is_file:
            continue  # The unselected alternative text body remains in original MIME.
        data = part.get_payload(decode=True)
        if part.defects:
            return None, 'message_decode_defects'
        if not isinstance(data, bytes):
            return None, 'attachment_decode_requires_review'
        if not data or len(data) > 10 * 1024 * 1024 or len(files) >= 8:
            return None, 'attachments_exceed_receiver_limits'
        mime = part.get_content_type()
        filename = part.get_filename() or f'inline-{part_number}' + FILE_TYPES.get(mime, '')
        if len(filename) > 255 or re.search(r'[\x00-\x1f\x7f"/\\]', filename):
            return None, 'attachment_filename_requires_review'
        if mime not in FILE_TYPES:
            return None, 'attachment_type_requires_review'
        if mime == DOCX_MIME and not text_intent:
            docx_parts.append(data)
        files.append({'file_id': f'part:{part_number}', 'filename': filename,
                      'data_url': f'data:{mime};base64,' + base64.b64encode(data).decode('ascii'),
                      'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    if sum(f['size_bytes'] for f in files) > 20 * 1024 * 1024:
        return None, 'attachments_exceed_receiver_limits'
    if not text_intent:
        docx_evidence = []
        for data in docx_parts:
            evidence, docx_reason = _extract_docx_intent_text(data)
            if docx_reason is not None:
                return None, docx_reason
            docx_evidence.append(evidence)
        if any(_has_site_copy_text_provenance(evidence) for evidence in docx_evidence):
            return None, 'possible_site_copy_requires_exact_source_id'
        if any(_has_procurement_language(evidence) for evidence in docx_evidence):
            return None, 'procurement_requires_source_mapping'
        if not any(_has_customer_intent('', evidence) for evidence in docx_evidence):
            return None, 'customer_intent_requires_review'
    return {'namespace': MAILBOX, 'source_id': key, 'delivery_id': key,
            'subject': subject, 'message_id': message_id,
            'lead': {'name': name, 'email': address, 'product': subject[:128],
                     'message': text}, 'files': files}, None
