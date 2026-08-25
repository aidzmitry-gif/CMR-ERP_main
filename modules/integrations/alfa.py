"""Коннектор к Альфа-Банку (host-to-host) — реализует ``BankGateway``.

Читает входящие зачисления (кредит) с расчётного счёта для авто-проводки оплат клиентов.

⚠ Деньги (PLATFORM #1): без кредов (``alfa_base_url``/``alfa_token`` пусты) → ``[]``. НЕ
отдаём demo-зачисления даже в dev: фабрикация «оплата пришла» пометит счета оплаченными
по несуществующим деньгам. Тесты подают фейковый шлюз. Реальные вызовы Альфы — слайс 3
(нужны договор host-to-host + сертификат/токен от банка); контракт ``fetch_incoming`` при
этом не меняется.
"""
from __future__ import annotations

from datetime import date


class AlfaBankClient:
    def __init__(self, base_url: str = "", token: str = "", account: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.account = account

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    async def fetch_incoming(self, since: date | None = None) -> list[dict]:
        if not self.configured:
            return []  # честная деградация: нет кредов — нет данных (не выдумываем оплаты)
        # TODO(slice-3): реальный host-to-host GET выписки Альфы (кредитовые операции),
        # маппинг в контракт BankGateway (ext_id/date/amount:str/payer_unp/purpose/...).
        # Явно падаем, а не молча [] — «настроено, но не реализовано» не должно выглядеть
        # как «зачислений нет» (тихая потеря денег недопустима). Роут вернёт 502.
        raise NotImplementedError(
            "Альфа host-to-host ещё не подключён (слайс 3): задан URL, но выгрузка не реализована"
        )
