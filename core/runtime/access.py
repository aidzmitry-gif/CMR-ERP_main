"""Backend-ограничение доступа к модулям по матрице ролей (``config/access.py``).

ASGI-middleware: сопоставляет путь запроса с префиксом модуля и, если роль текущего
пользователя (заголовок ``X-User-Roles``) не имеет доступа к этому модулю — отдаёт 403.
Системные роуты (health/system/approvals/telegram/docs) и суперроли — всегда открыты.

Это «тонкий» слой поверх роутов: он не знает о внутренностях модулей, только про
их префиксы (из реестра ``core.routers``) и UI-слаги (``config.access``). Реальная
авторизация (Keycloak OIDC) появится в части 5 — заголовок сменится на проверенный токен.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config.access import (
    CRM_INVITATION_OPERATOR_ROLE,
    IDENTITY_PROVISIONER_ROLE,
    ONBOARDING_ROLE,
    PACKAGE_TO_SLUG,
    is_package_allowed,
)

# Префиксы, открытые всегда (системные/инфраструктурные роуты и dev-доки).
OPEN_PREFIXES: tuple[str, ...] = (
    "/health", "/system", "/approvals", "/telegram", "/docs", "/redoc", "/openapi.json",
    "/marketing/seo/webhook",
)

# Сотрудник до подтверждения руководителя может открыть только сведения о
# собственном onboarding-доступе. Даже если ошибочно к токену будет добавлена
# ещё какая-то роль, presence onboarding остаётся fail-closed до явной смены
# набора ролей при подтверждении.
ONBOARDING_OPEN_PATHS: frozenset[str] = frozenset({"/health", "/system/access"})

# Технический service-account приглашений не получает общего системного доступа:
# ``/system`` содержит и маршруты без собственной permission dependency. Presence
# этой роли намеренно ограничивает смешанный токен тем же набором, чтобы ошибочная
# выдача дополнительной application-role не открыла CRM/HR или owner-insight.
IDENTITY_PROVISIONER_OPEN_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/system/users/departments",
        "/system/users/preflight",
        "/system/users/invite",
    }
)

CRM_INVITATION_OPERATOR_PATHS: frozenset[str] = frozenset({
    "/health", "/system/access", "/system/users/departments",
    "/system/users/crm-staff", "/system/users/preflight", "/system/users/invite",
    "/system/users/invitations", "/system/users/invitation-operations",
})
CRM_CONFIGURATION_PREFIXES = (
    "/sales/stages", "/sales/branding", "/sales/contract-templates", "/sales/prices",
    "/sales/plan-items", "/sales/plans", "/sales/telephony",
)

# These neighboring APIs can return/modify foreign deal data but do not yet
# implement numeric-owner scoping. Block them before the open system-prefix
# bypass. Shared SKU/reference endpoints remain available for normal deal work.
OWN_DEAL_UNSCOPED_PREFIXES: tuple[str, ...] = (
    "/leads", "/service", "/system/mdm/counterparty",
)
CRM_ROLES: frozenset[str] = frozenset({"sales_head", "sales", "sales_manager", "sales_cli"})


def roles_from_request(request: Request) -> list[str]:
    """Роли текущего пользователя — единый источник identity (``core.services.auth``).

    Делегирует в ``get_current_user`` (dev=заголовок ``X-User-Roles``, oidc=проверенный
    Keycloak-JWT), чтобы middleware и route-зависимости видели ОДНУ identity, а не две
    копии разбора. Fail-closed (SECURITY.md P0-1/P1): без заголовка/токена — «Гость».
    """
    from core.services.auth import get_current_user

    return get_current_user(request).roles


def build_prefix_map(core) -> list[tuple[str, str]]:
    """Собрать [(префикс, пакет-модуль)], отсортировано по длине префикса (длинные первыми).

    Берём только роутеры с непустым префиксом и только тех модулей, что реально
    ограничиваются (есть UI-слаг). Остальные (инфраструктура) — не попадают, т.е. открыты.
    """
    pairs = {
        reg.prefix: reg.module
        for reg in core.routers
        if reg.prefix and reg.module in PACKAGE_TO_SLUG
    }
    return sorted(pairs.items(), key=lambda kv: len(kv[0]), reverse=True)


class AccessControlMiddleware(BaseHTTPMiddleware):
    """Проверяет доступ к модулю по матрице ролей до выполнения роута."""

    def __init__(self, app, *, prefixes: list[tuple[str, str]]) -> None:
        super().__init__(app)
        self.prefixes = prefixes

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Health is intentionally dependency-free, including when the identity
        # database is degraded.  Every other route derives an effective user
        # before its first authorization decision.
        if path == "/health":
            return await call_next(request)

        from core.services.auth import (
            GUEST,
            EffectiveIdentityLookupError,
            get_current_user,
            resolve_effective_oidc_user,
        )

        claimed_user = get_current_user(request)
        if claimed_user.keycloak_user_id:
            db = request.app.state.core.services.db
            try:
                if db.session_factory is None:
                    db.init_engine()
                assert db.session_factory is not None
                async with db.session_factory() as session:
                    request.state.effective_current_user = await resolve_effective_oidc_user(
                        claimed_user, session
                    )
            except EffectiveIdentityLookupError:
                # Do not turn an unavailable local revocation/status store into
                # acceptance of an old JWT or disclose database details.
                return JSONResponse(
                    {"detail": "Проверка текущего доступа временно недоступна"},
                    status_code=403,
                )
            except Exception:
                return JSONResponse(
                    {"detail": "Проверка текущего доступа временно недоступна"},
                    status_code=403,
                )
        else:
            request.state.effective_current_user = claimed_user

        effective_user = request.state.effective_current_user
        if effective_user.local_status is not None and (
            effective_user.local_status not in {"active", "onboarding"}
            or GUEST in effective_user.roles
        ):
            if path != "/system/access":
                return JSONResponse(
                    {"detail": "Доступ сотрудника временно ограничен"}, status_code=403
                )

        roles = roles_from_request(request)
        if CRM_INVITATION_OPERATOR_ROLE in roles and path not in CRM_INVITATION_OPERATOR_PATHS:
            return JSONResponse({"detail": "Доступна только подготовка приглашений CRM"}, status_code=403)
        if effective_user.crm_restricted and path not in {"/health", "/system/access"}:
            crm_path = any(path == prefix or path.startswith(prefix + "/") for prefix in ("/sales", "/leads"))
            configuration_write = request.method not in {"GET", "HEAD", "OPTIONS"} and any(
                path == prefix or path.startswith(prefix + "/") for prefix in CRM_CONFIGURATION_PREFIXES
            )
            if not crm_path or request.method == "DELETE" or configuration_write:
                return JSONResponse({"detail": "Действие вне разрешённого рабочего доступа CRM"}, status_code=403)
        if (
            effective_user.deal_visibility == "own"
            and CRM_ROLES.intersection(roles)
            and any(path == prefix or path.startswith(prefix + "/")
                    for prefix in OWN_DEAL_UNSCOPED_PREFIXES)
        ):
            return JSONResponse(
                {"detail": "Этот раздел недоступен при личной видимости сделок"},
                status_code=403,
            )
        if ONBOARDING_ROLE in roles and path not in ONBOARDING_OPEN_PATHS:
            return JSONResponse(
                {"detail": "Доступ ограничен режимом ознакомления с системой"},
                status_code=403,
            )
        if (
            IDENTITY_PROVISIONER_ROLE in roles
            and path not in IDENTITY_PROVISIONER_OPEN_PATHS
        ):
            return JSONResponse(
                {"detail": "Технической identity-роли доступен только workflow приглашений"},
                status_code=403,
            )
        if path.startswith(OPEN_PREFIXES):
            return await call_next(request)

        for prefix, package in self.prefixes:
            if path == prefix or path.startswith(prefix + "/"):
                if not is_package_allowed(package, roles):
                    slug = PACKAGE_TO_SLUG.get(package, package)
                    return JSONResponse(
                        {"detail": f"Нет доступа к модулю: {slug}"}, status_code=403
                    )
                break
        return await call_next(request)
