from __future__ import annotations

import base64
from pathlib import Path

import pytest

from modules.leads import storage


def _data_url(content_type: str, payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode()
    return f"data:{content_type};base64,{encoded}"


def test_decode_data_url_returns_mime_and_bytes_and_rejects_malformed_input():
    assert storage.decode_data_url(_data_url("text/plain", b"hello")) == ("text/plain", b"hello")

    with pytest.raises(storage.AttachmentRejected, match="data-URI"):
        storage.decode_data_url("not-a-data-url")
    with pytest.raises(storage.AttachmentRejected, match="base64"):
        storage.decode_data_url("data:text/plain;base64,not valid!")


def test_save_read_and_delete_attachment_use_relative_path_and_safe_name(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(storage, "_DATA_DIR", tmp_path)

    path, size = storage.save_attachment(
        42,
        "../../contract scan?.pdf",
        "application/pdf",
        b"document",
    )
    assert Path(path).parts[0] == "42"
    assert ".." not in path
    assert size == len(b"document")
    assert storage.read_attachment(path) == b"document"

    storage.delete_attachment(path)
    assert not (tmp_path / path).exists()
    storage.delete_attachment(path)  # idempotent delete


@pytest.mark.parametrize(
    ("content_type", "payload_size"),
    [
        ("application/octet-stream", 1),
        ("application/pdf", 0),
        ("image/png", storage.MAX_SIZE_BYTES + 1),
    ],
)
def test_save_attachment_rejects_unsupported_empty_and_oversized_files(
    monkeypatch, tmp_path: Path, content_type: str, payload_size: int
):
    monkeypatch.setattr(storage, "_DATA_DIR", tmp_path)
    payload = b"x" * payload_size
    with pytest.raises(storage.AttachmentRejected):
        storage.save_attachment(1, "file", content_type, payload)


def test_attachment_path_guard_rejects_traversal(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(storage, "_DATA_DIR", tmp_path)
    with pytest.raises(storage.AttachmentRejected, match="путь"):
        storage.read_attachment("../outside.txt")
