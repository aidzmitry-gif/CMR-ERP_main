"""Модуль Integrations — реализация ModuleContract."""
from __future__ import annotations

from core.runtime.contract import ModuleContract, Permission
from core.runtime.core import Core
from modules.integrations import routes
from modules.integrations.alfa import AlfaBankClient
from modules.integrations.client import OneCClient
from modules.integrations.registry import RegistryClient
from modules.integrations.stock import StockService
from modules.integrations.sync_tick import tick_sync_out
from modules.integrations.telephony import ZruchnaClient


class IntegrationsModule(ModuleContract):
    name = "integrations"
    version = "0.1.0"
    api_prefix = "/integrations"

    def register(self, core: Core) -> None:
        core.include_router(routes.router, prefix=self.api_prefix)
        core.declare_permissions([
            Permission("integrations.sync", "Синхронизация с 1С"),
            Permission("integrations.telephony", "Инициация звонков (click-to-call)"),
        ])
        # опубликовать 1С-коннектор и складской шлюз в фасаде ядра — другие модули
        # пишут/читают в 1С и резервируют остатки через core.services, не импортируя
        # этот модуль (§2.4).
        core.services.onec = OneCClient(core.config.onec_base_url)
        core.services.stock = StockService()
        core.services.registry = RegistryClient(core.config.egr_base_url)
        # телефонный шлюз: исходящий звонок через облачную АТС zruchna. Входящие
        # события идут не через шлюз, а webhook'ом → шина (см. routes/telephony).
        core.services.telephony = ZruchnaClient(core.config.telephony_originate_url)
        # банковский шлюз (Альфа host-to-host): входящие зачисления клиентов → авто-проводка
        # оплат в finance. Пустые креды → пусто (честная деградация, не выдумываем оплаты).
        core.services.bank = AlfaBankClient(
            core.config.alfa_base_url, core.config.alfa_token, core.config.alfa_account
        )
        # M3: фоновый шаг исходящей выгрузки ERP → 1С (очередь sync_link → post_document)
        core.on_tick(tick_sync_out)


def get_module() -> ModuleContract:
    return IntegrationsModule()
