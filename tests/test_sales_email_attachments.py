from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi import HTTPException
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    TextStringObject,
)

from modules.sales.mail_attachments import validate_content

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.mark.parametrize(
    ("content_type", "main_path", "main_type", "main_xml"),
    [
        (DOCX, "word/document.xml", DOCX + ".main+xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>'),
        (XLSX, "xl/workbook.xml", XLSX + ".main+xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets/></workbook>'),
    ],
)
def test_standard_office_main_types_are_accepted(content_type, main_path, main_type, main_xml):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' + f'<Override PartName="/{main_path}" ContentType="{main_type}"/></Types>')
        archive.writestr(main_path, main_xml)
    validate_content(output.getvalue(), content_type)


def test_pdf_annotation_embedded_file_without_catalog_names_is_rejected():
    writer = PdfWriter()
    page = writer.add_blank_page(width=72, height=72)
    stream = DecodedStreamObject()
    stream.set_data(b"synthetic attachment")
    stream[NameObject("/Type")] = NameObject("/EmbeddedFile")
    file_spec = DictionaryObject({
        NameObject("/Type"): NameObject("/Filespec"),
        NameObject("/F"): TextStringObject("test.txt"),
        NameObject("/EF"): DictionaryObject({NameObject("/F"): writer._add_object(stream)}),
    })
    annotation = DictionaryObject({
        NameObject("/Subtype"): NameObject("/FileAttachment"),
        NameObject("/FS"): writer._add_object(file_spec),
    })
    page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
    output = BytesIO()
    writer.write(output)
    with pytest.raises(HTTPException) as exc:
        validate_content(output.getvalue(), "application/pdf")
    assert exc.value.status_code == 422


def _pdf(*, active=False) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    if active:
        writer._root_object[NameObject("/OpenAction")] = DictionaryObject(
            {
                NameObject("/S"): NameObject("/JavaScript"),
                NameObject("/JS"): TextStringObject("app.alert('blocked')"),
            }
        )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _ooxml(*, content_types: str, extra: dict[str, bytes] | None = None) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", b"<document/>")
        for name, value in (extra or {}).items():
            archive.writestr(name, value)
    return output.getvalue()


def _content_types(value: str) -> str:
    return (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        f'<Override PartName="/word/document.xml" ContentType="{value}"/>'
        "</Types>"
    )


def test_uploaded_pdf_is_structurally_parsed_and_benign_pdf_is_accepted():
    validate_content(_pdf(), "application/pdf")


def test_uploaded_pdf_rejects_active_open_action_and_malformed_bytes():
    for content in (_pdf(active=True), b"%PDF-1.7\nnot a pdf"):
        with pytest.raises(HTTPException) as exc:
            validate_content(content, "application/pdf")
        assert exc.value.status_code == 422


def test_issued_pdf_path_keeps_original_validation_without_upload_parser():
    validate_content(b"%PDF-1.7\nrendered original", "application/pdf", uploaded=False)


def test_ooxml_requires_semantic_main_override_not_comment_text():
    content = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        "<!-- wordprocessingml.document.main+xml -->"
        "</Types>"
    )
    with pytest.raises(HTTPException):
        validate_content(_ooxml(content_types=content), DOCX)


@pytest.mark.parametrize(
    "extra",
    [
        {"word/ExternalLinks/item.xml": b"bad"},
        {
            "word/_rels/document.xml.rels": (
                b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                b'<Relationship Id="r1" Type="https://example.test/ActiveX" Target="x"/>'
                b"</Relationships>"
            )
        },
    ],
)
def test_ooxml_rejects_external_link_components_and_active_relationships(extra):
    content = _content_types(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    )
    with pytest.raises(HTTPException):
        validate_content(_ooxml(content_types=content, extra=extra), DOCX)


def test_ooxml_rejects_duplicate_members():
    content_types = _content_types(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", b"<document/>")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("word/document.xml", b"<document/>")
    with pytest.raises(HTTPException):
        validate_content(output.getvalue(), DOCX)


def test_ooxml_rejects_forbidden_default_content_type():
    content = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    with pytest.raises(HTTPException):
        validate_content(_ooxml(content_types=content), DOCX)
