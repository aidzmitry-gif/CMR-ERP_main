"""Свип-доказательство write-RBAC инварианта (PLATFORM.md #2, security).

**Инвариант:** write-эндпоинт (POST/PUT/PATCH/DELETE) бизнес-модуля, к которому у роли
НЕТ доступа по ``config.access.ACCESS_MATRIX``, обязан вернуть **403 ДО выполнения роута**
(режет ``core.runtime.access.AccessControlMiddleware`` по префиксу модуля).

Тест САМ находит write-роуты из ``app.routes`` (не хардкод-список) → новый незащищённый
write-роут слаггнутого модуля уронит негативный свип, а новый *неслаггнутый* модуль с
write-роутами уронит coverage-guard. Гейт закрывается на уровне ЯДРА, не по-модульно.

Разбор реальности (аудит на 2026-07-02): 12 бизнес-модулей (sales/procurement/production/
wms/logistics/finance/marketing/service/hr/office/legal/knowledge) слаггнуты и гейтятся.
``integrations`` — инфраструктура без UI-слага (вебхуки телефонии/веб-лидов/почты + синк 1С):
внешние вызыватели не шлют ``X-User-Roles`` и аутентифицируются подписью (как открытый
``/marketing/seo/webhook``); гейтить его = ломать интеграции. Поэтому он — задокументированное
исключение, зафиксированное coverage-guard'ом (``_UNGATED_INFRA``), а не дыра.

⚠ Приложение и перечень роутов строятся в **runtime**-фикстурах (module-scope), НЕ на импорте
модуля: сборка на этапе collection была хрупкой в CI (пустой enumeration → свип тихо не гонялся).
Runtime-путь идентичен рабочей фикстуре ``api`` в conftest. Перечисление — циклом в тесте (не
parametrize), чтобы список роутов брался в runtime и один фейл отчитывался по ВСЕМ плохим роутам.
"""
from __future__ import annotations

import re
from collections import defaultdict

import pytest
from httpx import ASGITransport, AsyncClient

from config.access import (
    ROLE_ORDER,
    SUPER_ROLES,
    is_package_allowed,
)
from core.runtime.access import OPEN_PREFIXES, build_prefix_map
from core.runtime.app import create_app
from core.runtime.deps import get_session

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Синтетическая роль-«никто»: не super и НЕ в матрице → гарантированно лишена доступа к
# любому пакету. Нужна для модулей, доступных ВСЕМ реальным ролям (напр. ``knowledge``),
# где реального «отказника» подобрать нельзя. ASCII/HTTP-safe (кириллица в заголовке — mojibake).
_SYNTHETIC_DENIER = "__no_access__"

# Реальные не-super роли — для осмысленного «отказника» (напр. warehouse для crm).
_REAL_ROLES = [r for r in ROLE_ORDER if r not in SUPER_ROLES]

# Позитивный sanity: super-роль (полный доступ) → гейт всегда пропускает.
_OWNER_ROLE = "director"
assert _OWNER_ROLE in SUPER_ROLES  # инвариант выбора: владелец обязан быть super

# Неслаггнутые пакеты, для которых открытость write-роутов — осознанное решение (инфра).
# Coverage-guard падает, если появится НОВЫЙ неслаггнутый модуль с write-роутами вне списка.
_UNGATED_INFRA = frozenset({"integrations"})

_PARAM_RE = re.compile(r"\{[^}]+\}")


@pytest.fixture(scope="module")
def app():
    """FastAPI-приложение, собранное в RUNTIME (как conftest.api) — не на импорте модуля."""
    return create_app()


@pytest.fixture(scope="module")
def prefix_map(app):
    """[(prefix, package)] слаггнутых модулей, длинные префиксы первыми (как в middleware)."""
    return build_prefix_map(app.state.core)


def _package_for_path(prefix_map, path: str) -> str | None:
    """Пакет-модуль по самому длинному подходящему префиксу (только слаггнутые)."""
    for prefix, package in prefix_map:  # уже отсортировано: длинные первыми
        if path == prefix or path.startswith(prefix + "/"):
            return package
    return None


def _denying_role(package: str) -> str:
    """Роль, которой пакет НЕ доступен. Реальная (напр. warehouse), иначе синтетический «никто»."""
    for role in _REAL_ROLES:
        if not is_package_allowed(package, [role]):
            return role
    return _SYNTHETIC_DENIER


def _concrete_url(path: str) -> str:
    """Подставить фиктивные значения в path-параметры (тело роута не важно — важен 403 гейта)."""
    return _PARAM_RE.sub("1", path)


@pytest.fixture(scope="module")
def write_routes(app, prefix_map) -> list[tuple[str, str, str, str]]:
    """(method, concrete_url, package, denying_role) по write-роутам слаггнутых модулей.

    Пропускаем ``OPEN_PREFIXES`` (health/system/webhook — открыты намеренно) и роуты вне
    слаггнутых модулей (инфра/системные — гейт их не ограничивает; см. coverage-guard).
    """
    seen: set[tuple[str, str]] = set()
    routes: list[tuple[str, str, str, str]] = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path or path.startswith(OPEN_PREFIXES):
            continue
        package = _package_for_path(prefix_map, path)
        if package is None:
            continue
        denier = _denying_role(package)
        for method in sorted(methods & WRITE_METHODS):
            key = (method, path)
            if key in seen:
                continue
            seen.add(key)
            routes.append((method, _concrete_url(path), package, denier))
    return routes


@pytest.fixture
async def client(app, session):
    """ASGI-клиент БЕЗ дефолтной роли — роль каждый запрос задаёт явно (X-User-Roles)."""

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_sweep_discovered_module_write_routes(app, prefix_map, write_routes):
    """Свип реально что-то нашёл (пустой enumeration = ложно-зелёный).

    Заодно закрепляет: ключевые бизнес-модули присутствуют в наборе (защита от того, что
    ``create_app``/enumeration тихо сломались и routes исчезли)."""
    if not write_routes:
        # DIAGNOSTIC (CI-only фейл, локально не воспроизводится): показать, ЧТО видит окружение.
        from config.access import PACKAGE_TO_SLUG

        core = app.state.core
        registry = [(getattr(r, "prefix", None), getattr(r, "module", None)) for r in core.routers]
        n_routes = sum(1 for _ in app.routes)
        raise AssertionError(
            "свип не нашёл ни одного write-роута — enumeration сломан. DIAG: "
            f"app.routes={n_routes}; core.routers={len(core.routers)}; "
            f"prefix_map({len(prefix_map)})={prefix_map[:4]}; "
            f"registry(prefix,module)[:8]={registry[:8]}; "
            f"PACKAGE_TO_SLUG_keys={sorted(PACKAGE_TO_SLUG)}"
        )
    found_packages = {pkg for _, _, pkg, _ in write_routes}
    for expected in ("sales", "procurement", "wms", "finance"):
        assert expected in found_packages, f"нет write-роутов модуля {expected} — свип неполон"


def test_no_ungated_module_write_route(app, prefix_map):
    """Coverage-guard: у каждого неслаггнутого модуля с не-open write-роутами есть алиби.

    Модуль без UI-слага НЕ гейтится матрицей доступа. Для инфры (``integrations``) это
    осознанно (``_UNGATED_INFRA``). Появился НОВЫЙ такой модуль — тест падает: реши явно
    (дать слаг в ``config/access.py`` ИЛИ признать инфрой в ``_UNGATED_INFRA``)."""
    slugged = {pkg for _, pkg in prefix_map}
    # Пакет-владелец каждого роута из реестра модулей (не только слаггнутые), длинные префиксы первыми.
    owner_pairs = sorted(
        ((reg.prefix, reg.module) for reg in app.state.core.routers if reg.prefix),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )

    def owner_of(path: str) -> str | None:
        for prefix, module in owner_pairs:
            if path == prefix or path.startswith(prefix + "/"):
                return module
        return None

    ungated: dict[str, list[str]] = defaultdict(list)
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path or path.startswith(OPEN_PREFIXES):
            continue
        if not (methods & WRITE_METHODS):
            continue
        module = owner_of(path)
        if module and module not in slugged:
            ungated[module].append(path)

    unexpected = {m: paths for m, paths in ungated.items() if m not in _UNGATED_INFRA}
    assert not unexpected, (
        "Неслаггнутые модули с write-роутами вне allow-list инфры — гейт их НЕ ловит. "
        f"Реши явно (слаг в config/access.py ИЛИ _UNGATED_INFRA): {dict(unexpected)}"
    )


async def test_write_routes_denied_for_unauthorized_role(client, write_routes):
    """Негатив: роль без доступа к модулю → 403 (гейт режет до тела роута). Цикл по ВСЕМ роутам."""
    holes: list[str] = []
    for method, url, package, denier in write_routes:
        resp = await client.request(method, url, headers={"X-User-Roles": denier})
        if resp.status_code != 403:
            holes.append(f"{method} {url} [{package}!{denier}] → {resp.status_code}")
    assert not holes, (
        "write-RBAC дыры (роль без доступа к модулю получила НЕ 403 от гейта):\n" + "\n".join(holes)
    )


async def test_write_routes_allowed_for_owner_role(client, write_routes):
    """Позитив (sanity): super-роль (director) → НЕ 403 (гейт пропускает; тело может дать 4xx/5xx)."""
    false_blocks: list[str] = []
    for method, url, package, _denier in write_routes:
        resp = await client.request(method, url, headers={"X-User-Roles": _OWNER_ROLE})
        if resp.status_code == 403:
            false_blocks.append(f"{method} {url} [{package}]")
    assert not false_blocks, (
        f"гейт ложно режет владельца '{_OWNER_ROLE}' (403) на роутах:\n" + "\n".join(false_blocks)
    )
