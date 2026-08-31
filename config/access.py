"""Матрица доступа ролей к модулям — **единый источник истины**.

Здесь живёт финальная матрица «роль → список модулей» (UI-слаги). Её потребляют:
- backend-ограничение (`core/runtime/access.py`) — отдаёт 403 на роуты чужих модулей;
- фронт (`/system/access`) — прячет недоступные пункты сайдбара и рисует dev-переключатель роли.

Слаги модулей здесь — **UI-слаги** (как в сайдбаре): `crm`, `procurement`, … Часть из них
не совпадает с именем backend-пакета модуля (`crm` ↔ пакет `sales`); сопоставление — в
``SLUG_TO_PACKAGE``. Слаги `home`/`analytics`/`it` не имеют backend-модуля (фронтовые/системные).

Реального логина пока нет (Keycloak — часть 5): текущая роль приходит заголовком
``X-User-Roles`` (dev). Роли ``director``/``commercial`` и суперроль ``admin`` — полный доступ.
"""
from __future__ import annotations

from collections.abc import Iterable

# --- Финальная матрица: роль → модули (UI-слаги). Источник — согласованная матрица доступа. ---
ACCESS_MATRIX: dict[str, list[str]] = {
    # Машинная роль приглашений. Не показывается в UI и не назначается сотрудникам:
    # нужна только service account Keycloak, чтобы создать HR-карточку и отправить
    # приглашение без выдачи широкого ``system.write`` или супер-роли.
    # У сервисной учётной записи нет доступа ни к одному модулю. Операции
    # приглашения живут под /system/users и защищаются отдельными permissions;
    # иначе доступ к HR-модулю дал бы ей чтение и изменение кадровых данных.
    "identity_provisioner": [],
    # Единственная роль, выдаваемая новому сотруднику при первом входе. Она
    # намеренно не даёт доступ ни к одному бизнес-модулю: ``home`` — только
    # статический экран знакомства с ERP. Рабочие роль и отдел хранятся как
    # ожидающие подтверждения руководителя и назначаются отдельной операцией.
    "onboarding": ["home"],
    "director": [
        "home", "crm", "procurement", "production", "wms", "logistics", "finance",
        "marketing", "service", "hr", "office", "legal", "knowledge",
        "analytics", "spravochniki", "it",
    ],
    "commercial": [
        "home", "crm", "procurement", "production", "wms", "logistics", "finance",
        "marketing", "service", "hr", "office", "legal", "knowledge",
        "analytics", "spravochniki", "it",
    ],
    "assistant": ["home", "procurement", "logistics", "office", "knowledge", "spravochniki"],
    "sales_head": ["home", "crm", "marketing", "service", "knowledge", "analytics", "spravochniki"],
    "sales": ["home", "crm", "service", "knowledge"],
    # Keycloak realm role (go-live): алиас продавца — те же UI-модули, что у sales.
    "sales_manager": ["home", "crm", "service", "knowledge"],
    "sales_cli": ["home", "crm", "service", "knowledge"],
    "procurement": ["home", "procurement", "logistics", "knowledge", "spravochniki"],
    "warehouse": ["home", "wms", "logistics", "knowledge"],
    "logistics": ["home", "wms", "logistics", "knowledge"],
    "production": ["home", "production", "wms", "knowledge"],
    "finance": ["home", "logistics", "office", "knowledge"],
    "hr": [
        "home", "crm", "procurement", "production", "wms", "logistics", "finance",
        "marketing", "service", "hr", "office", "legal", "knowledge", "spravochniki",
    ],
}

# --- Человекочитаемые названия ролей (для dev-переключателя и подвала сайдбара). ---
ROLE_TITLES: dict[str, str] = {
    "onboarding": "Ознакомление с системой",
    "director": "Директор",
    "commercial": "Коммерческий директор",
    "assistant": "Помощник руководителя",
    "sales_head": "Продажи · РОП",
    "sales": "Продажи",
    "sales_manager": "Продажи · менеджер",
    "sales_cli": "Продажи · работа с клиентами",
    "procurement": "Закупки",
    "warehouse": "Склад",
    "logistics": "Логистика",
    "production": "Производство",
    "finance": "Финансы / офис",
    "hr": "Кадры (HR)",
}

# Порядок ролей в переключателе (как в матрице, сверху вниз).
ROLE_ORDER: list[str] = [
    "onboarding", "director", "commercial", "assistant", "sales_head", "sales", "sales_manager", "sales_cli",
    "procurement", "warehouse", "logistics", "production", "finance", "hr",
]

# Допустимые роли по отделам для управляемого приглашения сотрудника. Это гейт от
# случайной выдачи роли чужого отдела; сама роль остаётся источником backend RBAC.
DEPARTMENT_ROLES: dict[str, tuple[str, ...]] = {
    "Руководство": ("director", "commercial", "assistant"),
    "Продажи": ("sales_head", "sales", "sales_cli"),
    "Закупки": ("procurement",),
    "Склад": ("warehouse",),
    "Логистика": ("logistics",),
    "Производство": ("production",),
    "Финансы / офис": ("finance",),
    "Кадры (HR)": ("hr",),
}


def is_role_allowed_for_department(department: str, role: str) -> bool:
    """Можно ли назначить роль сотруднику выбранного отдела."""
    return role in DEPARTMENT_ROLES.get(department, ())

# Сотрудники компании (dev-логин). Единый источник: логин (ASCII) → ФИО + роль.
# Реальные люди из согласованной матрицы доступа. Пароля нет — это dev-вход (смена личности,
# не защита): настоящая аутентификация (Keycloak OIDC/MFA) — часть 5.
USERS: list[dict[str, str]] = [
    {"username": "kharkovich_d", "full_name": "Харькович Д.С.", "role": "director"},
    {"username": "kharkovich_s", "full_name": "Харькович С.Д.", "role": "commercial"},
    {"username": "shlyakhtina", "full_name": "Шляхтина Т.В.", "role": "assistant"},
    {"username": "ryazanov", "full_name": "Рязанов Е.В.", "role": "sales_head"},
    {"username": "makarov", "full_name": "Макаров", "role": "sales"},
    {"username": "karchevskaya", "full_name": "Карчевская", "role": "sales"},
    {"username": "kadurin", "full_name": "Кадурин", "role": "sales"},
    {"username": "maltsev", "full_name": "Мальцев", "role": "sales"},
    {"username": "kravets", "full_name": "Кравец", "role": "sales_cli"},
    {"username": "sarnatskaya", "full_name": "Сарнацкая", "role": "sales_cli"},
    {"username": "geniseva", "full_name": "Генисева А.А.", "role": "procurement"},
    {"username": "korneychuk", "full_name": "Корнейчук Я.В.", "role": "warehouse"},
    {"username": "matskevich", "full_name": "Мацкевич Е.М.", "role": "logistics"},
    {"username": "dym", "full_name": "Дым", "role": "production"},
    {"username": "korovkin", "full_name": "Коровкин", "role": "production"},
    {"username": "semenyuk", "full_name": "Семенюк", "role": "production"},
    {"username": "samedov", "full_name": "Самедов", "role": "production"},
    {"username": "rusinovich", "full_name": "Русинович", "role": "production"},
    {"username": "zhukovskaya", "full_name": "Жуковская О.Н.", "role": "finance"},
    {"username": "vedernikova", "full_name": "Ведерникова Д.В.", "role": "hr"},
]

# UI-слаг модуля → имя backend-пакета модуля (modules/<pkg>). Только реально существующие
# модули; `home`/`analytics`/`it` сюда не входят — у них нет HTTP-API для защиты.
SLUG_TO_PACKAGE: dict[str, str] = {
    "crm": "sales",
    "procurement": "procurement",
    "production": "production",
    "wms": "wms",
    "logistics": "logistics",
    "finance": "finance",
    "marketing": "marketing",
    "service": "service",
    "hr": "hr",
    "office": "office",
    "legal": "legal",
    "knowledge": "knowledge",
}
# Обратное сопоставление: пакет модуля → UI-слаг (для backend-ограничения по префиксу роута).
PACKAGE_TO_SLUG: dict[str, str] = {pkg: slug for slug, pkg in SLUG_TO_PACKAGE.items()}
# Лиды — часть CRM UI (префикс /leads); пакет не в SLUG_TO_PACKAGE (1:1 crm→sales).
PACKAGE_TO_SLUG["leads"] = "crm"

# Роли с полным доступом ко всему (минуя матрицу). "admin" — dev-суперюзер (ASCII, HTTP-safe).
SUPER_ROLES: frozenset[str] = frozenset({"admin", "director", "commercial"})

# Внемодульные права для технических субъектов. Они намеренно не выводятся из
# ACCESS_MATRIX: доступ к HR-модулю сам по себе не должен разрешать создание
# пользователей или изменение системных настроек.
IDENTITY_PROVISIONER_ROLE = "identity_provisioner"
ONBOARDING_ROLE = "onboarding"
IDENTITY_PROVISIONER_PERMISSIONS: frozenset[str] = frozenset(
    {"identity.invite.prepare", "identity.invite.send"}
)


def allowed_slugs(roles: Iterable[str]) -> set[str]:
    """Множество доступных UI-слагов для набора ролей (объединение по матрице)."""
    granted: set[str] = set()
    for role in roles:
        granted.update(ACCESS_MATRIX.get(role, ()))
    return granted


def is_super(roles: Iterable[str]) -> bool:
    """Есть ли у набора ролей полный доступ (Админ/Директор/Коммерческий)."""
    return bool(SUPER_ROLES.intersection(roles))


def is_slug_allowed(slug: str, roles: Iterable[str]) -> bool:
    """Доступен ли UI-слаг модуля данным ролям (суперроли — всегда да)."""
    roles = list(roles)
    return is_super(roles) or slug in allowed_slugs(roles)


def is_package_allowed(package: str, roles: Iterable[str]) -> bool:
    """Доступен ли backend-пакет модуля данным ролям.

    Пакеты без UI-слага (инфраструктура, напр. ``integrations``) — не ограничиваются.
    """
    slug = PACKAGE_TO_SLUG.get(package)
    if slug is None:
        return True
    return is_slug_allowed(slug, roles)


def user_by_username(username: str) -> dict[str, str] | None:
    """Найти сотрудника по логину (dev-логин). None — нет такого."""
    return next((u for u in USERS if u["username"] == username), None)


def users_with_titles() -> list[dict[str, str]]:
    """Список сотрудников с названием роли — для экрана входа (dev)."""
    return [{**u, "role_title": ROLE_TITLES.get(u["role"], u["role"])} for u in USERS]
