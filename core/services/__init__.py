"""Общие сервисы ядра и их сборка.

На этапе каркаса большинство сервисов — лёгкие заглушки с устойчивым контрактом:
их реализация наполняется в соответствующих частях дорожной карты (БД — часть 2,
шина — часть 3, Temporal — часть 4, auth — часть 5), а вызывающий код не меняется.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType

from core.services import sku_master
from core.services.approvals import ApprovalService
from core.services.auth import AuthService
from core.services.bank import BankGateway
from core.services.config import Settings, get_settings
from core.services.db import Database
from core.services.eventbus import OutboxEventBus
from core.services.landed_cost import LandedCostGateway
from core.services.litellm import LLMGateway
from core.services.onec import OneCGateway
from core.services.price_cost import PriceCostGateway
from core.services.registry import RegistryGateway
from core.services.stock import StockGateway
from core.services.telephony import TelephonyGateway
from core.services.temporal import TemporalService
from core.services.touch_history import TouchHistoryGateway

__all__ = ["Services", "build_services"]


@dataclass
class Services:
    """Контейнер общих сервисов, доступных модулям через ядро."""

    config: Settings
    event_bus: OutboxEventBus
    approvals: ApprovalService
    temporal: TemporalService
    db: Database
    auth: AuthService
    llm: LLMGateway
    # шлюзы 1С / складских остатков / реестра ЕГР наполняет модуль integrations
    # при register (часть 6/9/10); None — модуль не подключён
    onec: OneCGateway | None = None
    stock: StockGateway | None = None
    registry: RegistryGateway | None = None
    telephony: TelephonyGateway | None = None
    # банковский шлюз (Альфа host-to-host): входящие зачисления клиентов → авто-проводка
    # оплат в finance. Наполняет integrations; None — модуль не подключён.
    bank: BankGateway | None = None
    # себестоимость партии (landed cost) — наполняет модуль procurement; None — не подключён
    landed_cost: LandedCostGateway | None = None
    # цена продажи + себестоимость из учётной системы (1С) — reference-backed (справочник/MDM,
    # наполняется integrations из 1С) либо dev-фикстура; None → источник не подключён (честная
    # деградация, НЕ 0). Решение cost-price-from-1c-decision (PC1). В 1С напрямую не ходим.
    price_cost: PriceCostGateway | None = None
    # read-фасад мастер-входов landed cost по SKU (пошлина ТН ВЭД+НДС+вес/объём+провенанс) —
    # core-native (всегда доступен, не наполняется модулем); апстрим закупок/маржи. REF3-1.
    sku_master: ModuleType = sku_master
    # история касаний (звонки/письма/сделки) для 360° — наполняет sales; None — не подключён.
    # Несёт PII/коммерческую переписку → роут-потребитель защищён правом, реализация в sales
    # тоже проводит свою проверку прав (защита на обоих уровнях).
    touch_history: TouchHistoryGateway | None = None


def build_services() -> Services:
    """Собрать сервисы для текущего окружения."""
    settings = get_settings()
    event_bus = OutboxEventBus()
    return Services(
        config=settings,
        event_bus=event_bus,
        approvals=ApprovalService(event_bus),
        temporal=TemporalService(),
        db=Database(settings),
        auth=AuthService(),
        llm=LLMGateway(settings),
    )
