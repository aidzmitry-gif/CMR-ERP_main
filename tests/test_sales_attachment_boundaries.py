"""Bounded untrusted upload parsing; synthetic bytes only, no mail or filesystem."""
import base64
import struct
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from fastapi import HTTPException
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject

from modules.sales import mail_attachments as uploads
from tests.test_sales_email_attachments import DOCX, _content_types, _pdf


def _zip(entries):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, value in entries:
            if isinstance(name, str) and ("\\" in name or "\x00" in name):
                # Retain wire names: ZipInfo normalizes Windows separators and
                # NULs in its constructor, which would sanitize the fixture.
                raw = ZipInfo("synthetic-wire-name")
                raw.filename = raw.orig_filename = name
                raw.compress_type = ZIP_DEFLATED
                name = raw
            archive.writestr(name, value)
    return output.getvalue()


def _docx(extra=()):
    return _zip([
        ("[Content_Types].xml", _content_types(DOCX + ".main+xml")),
        ("word/document.xml", "<document/>"), *extra,
    ])


def _upload(data=b"synthetic text", **changes):
    return uploads.UploadSpec(**{
        "filename": "synthetic.txt", "content_type": "text/plain",
        "content_base64": base64.b64encode(data).decode("ascii"), **changes,
    })


@pytest.mark.parametrize("name", [None, "", "  ", "../synthetic.txt", "C:\\synthetic.txt", "..", "synthetic\x00.txt"])
def test_upload_filename_cannot_escape_or_hide_its_identity(name):
    with pytest.raises(HTTPException) as error:
        uploads.decode_upload(_upload(filename=name))
    assert error.value.status_code == 422


@pytest.mark.parametrize("name, content_type", [
    ("synthetic.exe", "text/plain"), ("synthetic.txt", "application/pdf"),
    ("synthetic.txt", "application/octet-stream"),
])
def test_filename_extension_and_supported_mime_type_must_agree(name, content_type):
    with pytest.raises(HTTPException) as error:
        uploads.decode_upload(_upload(filename=name, content_type=content_type))
    assert error.value.status_code == 422


@pytest.mark.parametrize("encoded, status", [("not base64!", 422), ("я", 422), ("AA", 422), (123, 413)])
def test_base64_input_is_not_coerced_or_partially_decoded(encoded, status):
    with pytest.raises(HTTPException) as error:
        uploads.decode_upload(_upload(content_base64=encoded))
    assert error.value.status_code == status


@pytest.mark.parametrize("content, content_type", [
    (b"", "text/plain"), (b"\xff", "text/plain"), (b"not PDF", "application/pdf"),
    (b"not PNG", "image/png"),
    (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"BAD!" + b"\0" * 13, "image/png"),
    (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 0, 1) + b"\0" * 5, "image/png"),
    (b"\xff\xd8\xffbroken", "image/jpeg"), (b"not ZIP", DOCX),
    (b"PK\x03\x04broken", DOCX), (b"synthetic", "application/octet-stream"),
])
def test_mime_label_cannot_disguise_invalid_file_content(content, content_type):
    with pytest.raises(HTTPException) as error:
        uploads.validate_content(content, content_type)
    assert error.value.status_code == 422


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "C:/drive.txt", "word\\bad.xml",
                                      "word//empty.xml", "word/./dot.xml", "word/../parent.xml",
                                      "word/hidden.xml\x00alias"])
def test_ooxml_members_cannot_escape_or_alias_archive_paths(name):
    with pytest.raises(HTTPException) as error:
        uploads.validate_content(_docx([(name, b"synthetic")]), DOCX)
    assert error.value.status_code == 422


def test_ooxml_symlink_member_is_refused_without_extracting_anything():
    link = ZipInfo("word/synthetic-link")
    link.create_system = 3
    link.external_attr = 0o120777 << 16
    with pytest.raises(HTTPException) as error:
        uploads.validate_content(_docx([(link, b"synthetic-target")]), DOCX)
    assert error.value.status_code == 422


@pytest.mark.parametrize("entries", [
    [("word/document.xml", "<document/>")],
    [("[Content_Types].xml", "<Types>"), ("word/document.xml", "<document/>")],
    [("[Content_Types].xml", "<NotTypes/>"), ("word/document.xml", "<document/>")],
    [("[Content_Types].xml", _content_types(DOCX + ".main+xml"))],
])
def test_office_package_requires_parsed_content_types_and_real_main_part(entries):
    with pytest.raises(HTTPException) as error:
        uploads.validate_content(_zip(entries), DOCX)
    assert error.value.status_code == 422


@pytest.mark.parametrize("attributes", [
    'Type="synthetic" Target="https://example.invalid/file"',
    'Type="synthetic" Target="file:///synthetic.txt"',
    'Type="synthetic" Target="\\\\synthetic-server/file"',
    'Type="synthetic" Target="local.xml" TargetMode="External"',
    'Type="synthetic" Target="embeddings/object.bin"',
])
def test_office_relationships_cannot_fetch_external_or_embedded_content(attributes):
    relationships = f'<Relationships><Relationship Id="r1" {attributes}/></Relationships>'
    with pytest.raises(HTTPException) as error:
        uploads.validate_content(_docx([("word/_rels/document.xml.rels", relationships)]), DOCX)
    assert error.value.status_code == 422


@pytest.mark.parametrize("action", ["/URI", "/Launch", "/SyntheticUnknownAction"])
def test_uploaded_pdf_action_allowlist_is_applied_inside_nested_objects(action):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer._root_object[NameObject("/Synthetic")] = DictionaryObject({
        NameObject("/A"): DictionaryObject({
            NameObject("/S"): NameObject(action),
            NameObject("/URI"): TextStringObject("https://example.invalid/synthetic"),
        }),
    })
    output = BytesIO()
    writer.write(output)
    with pytest.raises(HTTPException) as error:
        uploads.validate_content(output.getvalue(), "application/pdf")
    assert error.value.status_code == 422


def test_encrypted_pdf_is_rejected_before_becoming_a_mail_attachment():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("synthetic-test-password")
    output = BytesIO()
    writer.write(output)
    with pytest.raises(HTTPException) as error:
        uploads.decode_upload(_upload(output.getvalue(), filename="synthetic.pdf", content_type="application/pdf"))
    assert error.value.status_code == 422 and "Зашифрованное" in error.value.detail


@pytest.mark.parametrize("case", ["depth", "object_budget"])
def test_pdf_graph_traversal_has_explicit_resource_bounds(case):
    value = None
    if case == "depth":
        for _ in range(66):
            value = [value]
    else:
        value = list(range(20))
    with pytest.raises(HTTPException) as error:
        uploads._walk_pdf(value, seen=set(), state=[10000 if case == "depth" else 10])
    assert error.value.status_code == 422


def test_unexpected_pdf_dependency_failure_is_reported_without_private_details(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("SYNTHETIC_PRIVATE_VALUE")

    monkeypatch.setattr(uploads, "PdfReader", fail)
    with pytest.raises(HTTPException) as error:
        uploads.validate_content(_pdf(), "application/pdf")
    assert error.value.status_code == 422 and error.value.detail == "Некорректное PDF-вложение"
    assert "SYNTHETIC_PRIVATE_VALUE" not in str(error.value)


def test_encoded_and_decoded_attachment_limits_are_enforced():
    with pytest.raises(HTTPException) as encoded:
        uploads.decode_upload(_upload(content_base64="A" * (4 * uploads.MAX_ATTACHMENT_BYTES // 3 + 5)))
    assert encoded.value.status_code == 413
    with pytest.raises(HTTPException) as decoded:
        uploads.decode_upload(_upload(b"x" * (uploads.MAX_ATTACHMENT_BYTES + 1)))
    assert decoded.value.status_code == 413


def test_upload_count_and_aggregate_size_are_bounded():
    with pytest.raises(HTTPException) as count:
        uploads.uploads_from_payload([_upload()] * 11)
    assert count.value.status_code == 422
    item = _upload(b"x" * (uploads.MAX_ATTACHMENT_BYTES // 2 + 1))
    with pytest.raises(HTTPException) as size:
        uploads.uploads_from_payload([item, item])
    assert size.value.status_code == 413


def test_compressed_office_files_are_bounded_by_unpacked_bytes_and_member_count():
    for extra in (
        [(f"word/synthetic-{n}.xml", b"") for n in range(2049)],
        [("word/large-one.xml", b"x" * (8 * 1024 * 1024)),
         ("word/large-two.xml", b"x" * (8 * 1024 * 1024))],
    ):
        with pytest.raises(HTTPException) as error:
            uploads.validate_content(_docx(extra), DOCX)
        assert error.value.status_code == 422


def test_plain_utf8_upload_keeps_exact_content_and_digest_after_name_normalization():
    data = b"\xef\xbb\xbfSynthetic UTF8 text\n"
    item = uploads.decode_upload(_upload(data, filename="  synthetic.TXT ", content_type=" TEXT/PLAIN "))
    assert item.filename == "synthetic.TXT" and item.content_type == "text/plain"
    assert item.content == data and item.source_sha256 == uploads.digest(data)
    assert item.document_id is None and item.version is None
