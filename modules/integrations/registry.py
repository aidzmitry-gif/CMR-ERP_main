"""Реестр субъектов хозяйствования (ЕГР РБ) — обогащение контрагента по УНП (sales-28).

Mock: фиксированный справочник; при реальном интеграции — запрос в ЕГР (egr.gov.by)
по УНП. Контракт ответа (``unp/name/address/status``) сохранится.
"""
from __future__ import annotations


class RegistryClient:
    _DATA: dict[str, dict] = {
        "191234567": {"name": "ООО «Аккумулятор»", "address": "г. Минск, ул. Промышленная, 5", "status": "Действующий"},
        "190000001": {"name": "ООО «МеталлПром»", "address": "г. Гомель, ул. Заводская, 12", "status": "Действующий"},
        "190000002": {"name": "АО «СтройКомплект»", "address": "г. Брест, ул. Московская, 30", "status": "Действующий"},
        "190445566": {"name": "ООО «АльфаМеталл»", "address": "г. Минск, пр. Независимости, 95", "status": "Действующий"},
    }

    async def lookup(self, unp: str) -> dict | None:
        # TODO(part-10): реальный запрос в ЕГР (egr.gov.by) по УНП вместо mock
        data = self._DATA.get(unp.strip())
        if data is None:
            return None
        return {"unp": unp.strip(), **data}
