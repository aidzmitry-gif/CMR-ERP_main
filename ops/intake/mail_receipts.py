"""Prepare a new-intake request from a staged message; no network or mail writes.

Ambiguous mail remains reviewable with its original MIME. Never infer a site or
tender identity from an address alone. This module does not declare delivery.
"""
import base64
import hashlib
import re
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser

MAILBOX = 'admin@enersys.by'
FILE_TYPES = {
    'application/pdf': '.pdf',
    'application/msword': '.doc',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'image/jpeg': '.jpg', 'image/png': '.png',
}
SITE_COPY_MARKER_RE = re.compile(
    r'\b(?:form:\d+:result:\d+|mottor:[A-Za-z0-9._-]+:[A-Za-z0-9._-]+)\b', re.IGNORECASE
)
RS_FORM_MARKER_RE = re.compile(r'\bRS_FORM_ID\b', re.IGNORECASE)
RS_RESULT_MARKER_RE = re.compile(r'\bRS_RESULT_ID\b', re.IGNORECASE)


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
    combined = (subject + '\n' + text).casefold()
    if any(x in combined for x in ('тендер', 'закупк', 'маркетинговое исследование')):
        return None, 'procurement_requires_source_mapping'
    if not (any(x in combined for x in ('прошу', 'просим', 'нужен', 'нужны', 'запрос', 'заявка'))
            and any(x in combined for x in ('аккумулятор', 'батаре', 'элемент питан', 'акб'))):
        return None, 'customer_intent_requires_review'
    message_id = str(msg.get('Message-ID', '')).strip()
    if (len(message_id) > 998 or len(subject) > 4096 or len(text.encode()) > 256 * 1024
            or len(name) > 255 or len(address) > 128 or '\x00' in name + address + subject + text):
        return None, 'message_exceeds_receiver_limits'
    identity = message_id or f'{MAILBOX}:{uidvalidity}:{uid}'
    key = 'mail:' + hashlib.sha256(identity.encode()).hexdigest()
    files = []
    # walk() includes inline files nested under multipart/related. Direct-only
    # iter_attachments() silently omitted those files from a delivered receipt.
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
        files.append({'file_id': f'part:{part_number}', 'filename': filename,
                      'data_url': f'data:{mime};base64,' + base64.b64encode(data).decode('ascii'),
                      'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    if sum(f['size_bytes'] for f in files) > 20 * 1024 * 1024:
        return None, 'attachments_exceed_receiver_limits'
    return {'namespace': MAILBOX, 'source_id': key, 'delivery_id': key,
            'subject': subject, 'message_id': message_id,
            'lead': {'name': name, 'email': address, 'product': subject[:128],
                     'message': text}, 'files': files}, None
