"""Матрица доступа: единый источник (config/access.py) + backend-ограничение по ролям.

Без БД: проверяем `/system/access`, что суперроли/дефолт открыты, а ограниченная роль
получает 403 на чужой модуль. Ограничение — ASGI-middleware до выполнения роута, поэтому
доступ к чужому модулю отсекается даже на несуществующем пути под его префиксом.
"""
from fastapi.testclient import TestClient

from config.access import (
    allowed_slugs,
    is_package_allowed,
    is_slug_allowed,
    user_by_username,
)
from core.runtime.app import create_app

client = TestClient(create_app())


# --- единый источник: матрица и хелперы ---
def test_system_access_exposes_matrix_and_roles():
    r = client.get("/system/access")
    assert r.status_code == 200
    data = r.json()
    # директор видит всё; продажи — ограниченный набор
    assert "crm" in data["matrix"]["director"]
    assert set(data["matrix"]["sales"]) == {"home", "crm", "service", "knowledge"}
    titles = {role["slug"]: role["title"] for role in data["roles"]}
    assert titles["director"] == "Директор"
    assert titles["sales_head"] == "Продажи · РОП"


def test_helpers_map_slug_to_package():
    # UI-слаг crm соответствует backend-пакету sales
    assert is_slug_allowed("crm", ["sales"]) is True
    assert is_package_allowed("sales", ["sales"]) is True
    assert is_package_allowed("sales", ["procurement"]) is False
    # инфраструктурный пакет без слага не ограничивается
    assert is_package_allowed("integrations", ["sales"]) is True
    # объединение по нескольким ролям
    assert "marketing" in allowed_slugs(["sales", "sales_head"])


# --- backend-ограничение ---
def test_default_role_is_superuser():
    # без заголовка роли — dev-Админ, полный доступ
    assert client.get("/sales/ping").status_code == 200


def test_super_roles_have_full_access():
    # роли передаются по сети ASCII-слагами; «Админ» — дефолт без заголовка (см. выше)
    for role in ("director", "commercial"):
        r = client.get("/sales/ping", headers={"X-User-Roles": role})
        assert r.status_code == 200, role


def test_role_with_module_is_allowed():
    # роль «продажи» имеет доступ к crm (= пакет sales)
    r = client.get("/sales/ping", headers={"X-User-Roles": "sales"})
    assert r.status_code == 200


def test_role_without_module_gets_403():
    # роль «закупки» не имеет crm → 403 на /sales/*
    r = client.get("/sales/ping", headers={"X-User-Roles": "procurement"})
    assert r.status_code == 403
    assert "crm" in r.json()["detail"]


def test_system_routes_always_open():
    # системные роуты открыты даже для ограниченной роли
    assert client.get("/health", headers={"X-User-Roles": "sales"}).status_code == 200
    assert client.get("/system/access", headers={"X-User-Roles": "sales"}).status_code == 200


# --- dev-логин: сотрудники → роль ---
def test_user_resolves_to_role():
    u = user_by_username("makarov")
    assert u is not None and u["role"] == "sales"
    assert user_by_username("ryazanov")["role"] == "sales_head"
    assert user_by_username("нет-такого") is None


def test_system_users_endpoint():
    r = client.get("/system/users")
    assert r.status_code == 200
    users = r.json()["users"]
    director = next(u for u in users if u["username"] == "kharkovich_d")
    assert director["role"] == "director"
    assert director["role_title"] == "Директор"
    # у каждого сотрудника есть ФИО и название роли
    assert all(u.get("full_name") and u.get("role_title") for u in users)


# --- dev-логин: сотрудники → роль ---
def test_system_users_lists_employees():
    r = client.get("/system/users")
    assert r.status_code == 200
    users = {u["username"]: u for u in r.json()["users"]}
    assert users["ryazanov"]["role"] == "sales_head"
    assert users["ryazanov"]["role_title"] == "Продажи · РОП"
    assert users["makarov"]["role"] == "sales"


def test_user_by_username_resolves_role():
    assert user_by_username("geniseva")["role"] == "procurement"
    assert user_by_username("nope") is None
