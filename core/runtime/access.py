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

from config.access import PACKAGE_TO_SLUG, is_package_allowed

# Префиксы, открытые всегда (системные/инфраструктурные роуты и dev-доки).
OPEN_PREFIXES: tuple[str, ...] = (
    "/health", "/system", "/approvals", "/telegram", "/docs", "/redoc", "/openapi.json",
)


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
        if path.startswith(OPEN_PREFIXES):
            return await call_next(request)

        roles = roles_from_request(request)
        for prefix, package in self.prefixes:
            if path == prefix or path.startswith(prefix + "/"):
                if not is_package_allowed(package, roles):
                    slug = PACKAGE_TO_SLUG.get(package, package)
                    return JSONResponse(
                        {"detail": f"Нет доступа к модулю: {slug}"}, status_code=403
                    )
                break
        return await call_next(request)
