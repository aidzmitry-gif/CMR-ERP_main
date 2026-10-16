"""Модуль Office (Офис-менеджер) — реализация ModuleContract.

Регистрирует в ядре: API-роутер ``/office``, виджет панели владельца, права RBAC
и роль «Офис-менеджер», а также подписки на события соседних отделов — это и есть
связи модуля (Sales → office, Склад → office, Логистика → office, Финансы → office).
Исходящие связи office → отделы реализованы emit-ами в ``routes.py``/``events.py``.
"""
from __future__ import annotations

from core.runtime.contract import ModuleContract, Permission, Role, Widget
from core.runtime.core import Core
from modules.office import events, routes

# Права RBAC модуля.
PERMISSIONS = [
    Permission("office.doc.read", "Просмотр документов по сделкам"),
    Permission("office.doc.write", "Создание и изменение документов"),
    Permission("office.stage.move", "Перевод документа по стадиям воронки"),
    Permission("office.carrier.request", "Создание заявки перевозчику на доставку по РБ"),
    Permission("office.shipping.associate", "Подтверждение связи заявки со счётом"),
    Permission("office.shipping.review.assign", "Назначение reviewer конкретного OfficeDoc"),
    Permission("office.shipping.review.revoke", "Отзыв reviewer конкретного OfficeDoc"),
]


class OfficeModule(ModuleContract):
    name = "office"
    version = "0.3.0"
    api_prefix = "/office"

    def register(self, core: Core) -> None:
        from modules.office.shipping_producer import OfficeShippingProducer

        core.services.shipping_producer.register("office", OfficeShippingProducer(core))
        # API + виджет панели владельца
        core.include_router(routes.router, prefix=self.api_prefix)
        core.register_widget(Widget("office", "Офис-менеджер", source="office.docs"))

        # RBAC: права и роль офис-менеджера
        core.declare_permissions(PERMISSIONS)
        core.declare_role(Role("Офис-менеджер", permissions=tuple(p.code for p in PERMISSIONS if not p.code.startswith("office.shipping."))))
        # Canonical role slugs. Individual assignment, deal visibility and
        # organization authority remain mandatory inside the source adapter.
        core.declare_role(Role("assistant", ("office.doc.read", "office.carrier.request")))
        core.declare_role(Role("finance", ("office.doc.read", "office.carrier.request", "office.shipping.associate")))

        # Входящие связи с отделами — подписки на события шины
        core.subscribe("sales.deal.won", events.on_deal_won)                    # ← CRM/Sales
        core.subscribe("wms.shipment.completed", events.on_shipment_completed)  # ← Склад
        core.subscribe("logistics.delivery.delivered", events.on_delivery_delivered)  # ← Логистика
        core.subscribe("logistics.delivery.tracking", events.on_delivery_tracking)    # ← Логистика (статус в пути)
        core.subscribe("finance.payment.received", events.on_payment_received)  # ← Финансы


def get_module() -> ModuleContract:
    return OfficeModule()
