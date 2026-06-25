"""Реестр субъектов хозяйствования (ЕГР РБ) — обогащение контрагента по УНП (sales-28).

При заданном ``base_url`` — реальный HTTP-запрос в ЕГР (egr.gov.by) по УНП; пустой
``base_url`` → mock-справочник (dev/прототип). Контракт ответа (``unp/name/address/status``)
один и тот же — потребители (карточка, реквизиты договора) не меняются при включении живого ЕГР.
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("aios.integrations.registry")


class RegistryClient:
    _DATA: dict[str, dict] = {
        "191234567": {"name": "ООО «Аккумулятор»", "address": "г. Минск, ул. Промышленная, 5", "status": "Действующий"},
        "190000001": {"name": "ООО «МеталлПром»", "address": "г. Гомель, ул. Заводская, 12", "status": "Действующий"},
        "190000002": {"name": "АО «СтройКомплект»", "address": "г. Брест, ул. Московская, 30", "status": "Действующий"},
        "190445566": {"name": "ООО «АльфаМеталл»", "address": "г. Минск, пр. Независимости, 95", "status": "Действующий"},
    }

    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url.rstrip("/")

    async def lookup(self, unp: str) -> dict | None:
        """Карточка контрагента по УНП. ``None`` — не найден/сервис недоступен (graceful)."""
        unp = unp.strip()
        if not unp:
            return None
        if self.base_url:
            return await self._lookup_remote(unp)
        data = self._DATA.get(unp)
        return {"unp": unp, **data} if data else None

    async def _lookup_remote(self, unp: str) -> dict | None:
        """Реальный запрос в ЕГР. Ошибка/таймаут/не-200 → None (не роняем вызывающего)."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/{unp}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            row = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("ЕГР lookup %s не удался: %s", unp, exc)
            return None
        # маппинг полей ЕГР → наш контракт (имена полей уточняются под реальный ответ ЕГР)
        return {
            "unp": unp,
            "name": row.get("vfullname") or row.get("vname") or row.get("name", ""),
            "address": row.get("vaddress") or row.get("address", ""),
            "status": row.get("vstate") or row.get("status", ""),
        }
