from __future__ import annotations

from core.runtime.contract import ModuleContract, Reference, ReferenceColumn, Widget
from modules.accounting import (  # noqa: F401
    bank_import,
    expense_models,
    expense_routes,
    models,
    routes,
    service,
    settlement_offsets,
)
from modules.accounting.gateway import AccountingService


async def on_posting_requested(payload, ctx):
    # Organization/source binding is supplied by a trusted module adapter, not a public webhook.
    org_id = payload.get("organization_id")
    if not isinstance(org_id, int) or isinstance(org_id, bool):
        raise service.AccountingError("Source event requires a resolved organization")
    routes.valid_month(payload["month"])
    await service.receive(ctx.session, org_id, payload["event_key"],
                          payload["month"], payload["posting"])


class AccountingModule(ModuleContract):
    name = "accounting"
    version = "0.1.0"
    api_prefix = "/accounting"

    def register(self, core):
        core.services.accounting = AccountingService(core.services)
        core.include_router(routes.router, prefix=self.api_prefix)
        core.include_router(expense_routes.router, prefix=self.api_prefix)
        core.subscribe("accounting.posting.requested", on_posting_requested)
        core.register_widget(Widget("accounting", "Бухгалтерия", source="accounting.entries"))
        core.register_reference(Reference(
            key="accounting.chart", title="План счетов Беларуси", department="Финансы",
            owner_schema="accounting", endpoint="/accounting/catalog/accounts",
            columns=(ReferenceColumn("code", "Счёт", editable=False),
                     ReferenceColumn("title", "Наименование", editable=False),
                     ReferenceColumn("parent", "Родительский счёт", editable=False),
                     ReferenceColumn("off_balance", "Забалансовый", "bool", editable=False),
                     ReferenceColumn("edition_status", "Редакция", editable=False)),
            permissions=("refs.view",), archivable=False, versioned=True, ai_exposed=False,
            description="Типовой справочник по постановлению № 50: базовая транскрипция через 2022 год "
                        "с очередью проверки изменений № 73 и № 126. Нормативная редакция 2026 года "
                        "не подтверждена; рабочие счета ведутся по юрлицам.",
        ))


def get_module():
    return AccountingModule()
