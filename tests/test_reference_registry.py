"""Реестр-витрина «Справочники»: контракт register_reference + системные роуты каталога.

Без БД: каталог читается из реестра ядра (``core.references``), не из таблиц. Проверяем
группировку по отделам, атрибуцию владельцу и узкий каталог для AI (только ai_exposed).
"""
from fastapi.testclient import TestClient

from core.runtime.app import create_app
from core.runtime.contract import Reference

client = TestClient(create_app())


def test_references_grouped_by_department():
    r = client.get("/system/references")
    assert r.status_code == 200
    departments = r.json()["departments"]
    # системные справочники ядра разложены по отделам дерева
    assert "Система" in departments
    assert "Общие" in departments
    by_key = {ref["key"]: ref for refs in departments.values() for ref in refs}
    # и reference data, и мастер-данные зарегистрированы ядром
    assert "core.units" in by_key
    assert "core.counterparties" in by_key
    # данные у владельца (public), регистрация атрибутирована ядру
    cp = by_key["core.counterparties"]
    assert cp["owner_schema"] == "public"
    assert cp["module"] == "core"
    assert cp["columns"]  # метаданные колонок прокинуты
    # историчный справочник помечен versioned, простой — нет
    assert by_key["core.currency_rates"]["versioned"] is True
    assert by_key["core.units"]["versioned"] is False


def test_ai_catalog_contains_only_exposed():
    r = client.get("/system/references/ai-catalog")
    assert r.status_code == 200
    refs = r.json()["references"]
    keys = {ref["key"] for ref in refs}
    # ai_exposed=True — попадают в каталог для AI
    assert {"core.counterparties", "core.currency_rates", "core.skus"} <= keys
    # ai_exposed=False — не попадают
    assert "core.banks" not in keys
    assert "core.contacts" not in keys
    # узкая «машинная» форма колонок: только name/type/semantic, без UI-полей
    sample = next(ref for ref in refs if ref["key"] == "core.counterparties")
    assert set(sample["columns"][0]) == {"name", "type", "semantic"}


def test_register_reference_is_attributed_to_current_module():
    """Регистрация атрибутируется текущему модулю автоматически (как прочие register_*)."""
    app = create_app()
    core = app.state.core
    core._begin("demo")
    core.register_reference(
        Reference(
            key="demo.thing",
            title="Тест",
            department="Демо",
            owner_schema="demo",
            endpoint="/demo/refs/thing",
        )
    )
    core._end("demo")
    last = core.references[-1]
    assert last.module == "demo"
    assert last.reference.key == "demo.thing"


def test_register_owned_reference_attributes_owner_without_loaded_modules():
    """Публичный путь регистрации владельцем — без приватного _current и без loaded_modules."""
    app = create_app()
    core = app.state.core
    before = list(core.loaded_modules)
    core.register_owned_reference(
        "core",
        Reference(
            key="core.demo",
            title="Демо",
            department="Система",
            owner_schema="public",
            endpoint="/system/refs/demo",
        ),
    )
    last = core.references[-1]
    assert last.module == "core"
    assert last.reference.key == "core.demo"
    assert core.loaded_modules == before  # владелец-ядро не попал в loaded_modules
