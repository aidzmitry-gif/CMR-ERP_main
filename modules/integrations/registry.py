"""Публичный ГРП МНС: GET по УНП, проверка записи и метаданные источника.

Историческое имя настройки egr_base_url сохранено. Пустой endpoint закрыт;
демо-справочник доступен только при явном allow_demo, без сетевого fallback.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime

import httpx

from core.services.registry import RegistryError

logger = logging.getLogger("aios.integrations.registry")
MNS_ENDPOINT = "https://grp.nalog.gov.by/api/grp-public/data"


def _invalid_response() -> RegistryError:
    return RegistryError("invalid_upstream", "Реестр МНС вернул некорректные данные", 502)


def _text(row: dict, key: str) -> str:
    value = row.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _invalid_response()
    return value.strip()


def _date(row: dict, key: str) -> str | None:
    value = _text(row, key)
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise _invalid_response() from exc


class RegistryClient:
    _DATA: dict[str, dict] = {
        "191234567": {"name": "ООО «Аккумулятор»", "address": "г. Минск, ул. Промышленная, 5", "status": "Действующий"},
        "190000001": {"name": "ООО «МеталлПром»", "address": "г. Гомель, ул. Заводская, 12", "status": "Действующий"},
        "190000002": {"name": "АО «СтройКомплект»", "address": "г. Брест, ул. Московская, 30", "status": "Действующий"},
        "190445566": {"name": "ООО «АльфаМеталл»", "address": "г. Минск, пр. Независимости, 95", "status": "Действующий"},
    }

    def __init__(self, base_url: str = "", *, allow_demo: bool = False) -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.allow_demo = allow_demo

    async def lookup(self, unp: str) -> dict | None:
        """Legacy: необязательное обогащение договора, любой ожидаемый отказ → None."""
        try:
            return await self.lookup_strict(unp)
        except RegistryError as exc:
            logger.info("Registry optional lookup: %s", exc.code)
            return None

    async def lookup_strict(self, unp: str) -> dict:
        """Только 9 ASCII цифр, без удаления букв или подстановки УНП в чужой ответ."""
        unp = unp.strip()
        if not re.fullmatch(r"[0-9]{9}", unp):
            raise RegistryError("bad_input", "УНП — 9 цифр", 422)
        if self.base_url:
            # Только проверенный провайдер может называться mns_grp. URL не берём от браузера.
            if self.base_url != MNS_ENDPOINT:
                raise RegistryError("unconfigured", "Источник МНС настроен некорректно", 503)
            return await self._lookup_remote(unp)
        if not self.allow_demo:
            raise RegistryError("unconfigured", "Реестр МНС не подключён", 503)
        data = self._DATA.get(unp)
        if data is None:
            raise RegistryError("not_found", "По УНП ничего не найдено", 404)
        return {
            "unp": unp, **data, "source": "demo", "source_url": None,
            "fetched_at": datetime.now(UTC).isoformat(),
        }

    async def _lookup_remote(self, unp: str) -> dict:
        url = httpx.URL(self.base_url, params={"unp": unp, "charset": "UTF-8", "type": "json"})
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                resp = await client.get(url)
        except httpx.TimeoutException as exc:
            raise RegistryError("timeout", "Реестр МНС не ответил вовремя", 503) from exc
        except httpx.HTTPError as exc:
            raise RegistryError("unreachable", "Реестр МНС недоступен", 503) from exc
        if resp.status_code == 404:
            raise RegistryError("not_found", "По УНП ничего не найдено", 404)
        if resp.status_code == 429:
            retry = resp.headers.get("retry-after", "")
            # Ограниченное число секунд, без переноса произвольного заголовка и автоповторов.
            retry_after = min(300, max(1, int(retry))) if re.fullmatch(r"[0-9]{1,9}", retry) else None
            raise RegistryError("rate_limited", "Слишком много запросов к реестру МНС", 429, retry_after)
        if resp.status_code in (401, 403):
            raise RegistryError("upstream_access_denied", "Источник МНС отклонил доступ", 502)
        if resp.status_code != 200:
            raise RegistryError("upstream_error", "Ошибка сервиса МНС", 502)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise _invalid_response() from exc
        if not isinstance(payload, dict) or "row" not in payload:
            raise _invalid_response()
        row = payload["row"]
        if row is None or row == {} or row == []:
            raise RegistryError("not_found", "По УНП ничего не найдено", 404)
        if not isinstance(row, dict):
            raise _invalid_response()
        returned_unp = row.get("vunp")
        # JSON реестра может кодировать УНП числом; bool/float не считаются УНП.
        if type(returned_unp) is int:
            returned_unp = str(returned_unp)
        if not isinstance(returned_unp, str) or returned_unp.strip() != unp:
            raise _invalid_response()
        name = _text(row, "vnaimp")
        if not name:
            raise _invalid_response()
        status_code = row.get("ckodsost")
        if type(status_code) is int:
            status_code = str(status_code)
        if status_code is not None and not isinstance(status_code, str):
            raise _invalid_response()
        return {
            "unp": returned_unp.strip(), "name": name,
            "short_name": _text(row, "vnaimk") or None,
            "address": _text(row, "vpadres"), "status": _text(row, "vkods"),
            "status_code": (status_code.strip() or None) if status_code is not None else None,
            "registered_at": _date(row, "dreg"), "closed_at": _date(row, "dlikv"),
            "source": "mns_grp", "source_url": str(url),
            "fetched_at": datetime.now(UTC).isoformat(),
        }
