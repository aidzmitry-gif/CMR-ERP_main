"""Юнит-тесты инфраструктуры коннекторов (без сети, без внешних сервисов).

Покрывает требования DoD из connectors_spec.md, не зависящие от конкретного
источника: детерминированное имя файла (идемпотентность очереди, FR-3),
атомарную запись записи (FR-4), сквозной ключ unit_id (FR-1) и хранилище
курсоров StateStore (FR-6, NFR-1).
"""
from __future__ import annotations

import hashlib
import json

import pytest

from connectors import run
from connectors import state as state_module
from connectors.models import RawRecord
from connectors.state import NullStateStore, StateStore

pytestmark = pytest.mark.unit


def _rec(source="bitrix_call", source_id="123", record_type="call", **kw):
    return RawRecord(source=source, source_id=source_id, record_type=record_type,
                     payload={"ID": source_id}, **kw)


# --- FR-1: unit_id ---------------------------------------------------------

def test_unit_id_is_source_colon_source_id():
    assert _rec(source="onec", source_id="Catalog:ABC").unit_id == "onec:Catalog:ABC"


def test_to_dict_roundtrips_all_fields():
    rec = _rec(media_path="data/media/call_1.mp3", source_url="https://x")
    d = rec.to_dict()
    assert d["source"] == "bitrix_call"
    assert d["media_path"] == "data/media/call_1.mp3"
    assert d["source_url"] == "https://x"
    assert "unit_id" not in d  # property, не поле dataclass


# --- FR-3: детерминированное имя файла -------------------------------------

def test_filename_is_deterministic_and_matches_spec():
    rec = _rec()
    expected_digest = hashlib.sha1(b"bitrix_call:123").hexdigest()[:16]
    name = run._filename(rec)
    assert name == f"bitrix_call_{expected_digest}.json"
    # повторный вызов на эквивалентной записи даёт ТО ЖЕ имя (идемпотентность)
    assert run._filename(_rec()) == name


def test_filename_differs_for_different_unit_ids():
    assert run._filename(_rec(source_id="1")) != run._filename(_rec(source_id="2"))


# --- FR-3 + FR-4: persist пишет атомарно и идемпотентно --------------------

def test_persist_writes_record_and_is_idempotent(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    monkeypatch.setattr(run, "_inbox_dir", str(inbox))

    run.persist(_rec())
    files = list(inbox.glob("*.json"))
    assert len(files) == 1, "одна запись → один файл"

    # повторная выгрузка той же сущности перезаписывает тот же файл, не плодит дубли
    run.persist(_rec())
    assert len(list(inbox.glob("*.json"))) == 1

    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["source"] == "bitrix_call"
    assert data["source_id"] == "123"
    # временный .tmp не должен остаться
    assert not list(inbox.glob("*.tmp"))


# --- FR-6 + NFR-1: StateStore (курсоры, атомарность, перезагрузка) ---------

def test_statestore_get_default_when_missing(tmp_path):
    store = StateStore(str(tmp_path / "state.json"))
    assert store.get("nope") is None
    assert store.get("nope", 0) == 0


def test_statestore_persists_and_reloads_from_disk(tmp_path):
    path = str(tmp_path / "state.json")
    store = StateStore(path)
    store.set("bitrix_calls_last_id", 42)
    store.set("onec_cursor", "2026-06-10T00:00:00")

    # новый экземпляр читает с диска → рестарт продолжает с курсора
    reloaded = StateStore(path)
    assert reloaded.get("bitrix_calls_last_id") == 42
    assert reloaded.get("onec_cursor") == "2026-06-10T00:00:00"


def test_null_statestore_never_persists():
    store = NullStateStore()
    store.set("k", 1)
    assert store.get("k") is None


def test_statestore_flush_is_atomic_no_tmp_left(tmp_path):
    path = tmp_path / "state.json"
    store = StateStore(str(path))
    store.set("k", "v")
    assert path.exists()
    # mkstemp-файлы подменяются через os.replace — мусора в каталоге нет
    leftovers = [p for p in tmp_path.iterdir() if p.name != "state.json"]
    assert leftovers == []


def test_statestore_retries_transient_windows_replace_lock(tmp_path, monkeypatch):
    """Антивирус может кратко удерживать только что созданный файл на Windows."""
    path = tmp_path / "state.json"
    original_replace = state_module.os.replace
    attempts = 0

    def transient_lock(source, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("temporary file lock")
        original_replace(source, target)

    monkeypatch.setattr(state_module.os, "name", "nt")
    monkeypatch.setattr(state_module.os, "replace", transient_lock)

    StateStore(str(path)).set("cursor", "value")

    assert attempts == 3
    assert json.loads(path.read_text(encoding="utf-8")) == {"cursor": "value"}
