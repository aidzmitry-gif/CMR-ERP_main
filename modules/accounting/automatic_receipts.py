"""Choose explicit native purchase accounts; preserve canonical posting arithmetic."""
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from core.domain.models import Sku
from core.domain.reference import NomenclatureCategory
from core.services.procurement import ReceiptAccountingOptions
from modules.accounting import service
from modules.accounting.models import Policy
from modules.accounting.schemas import DocumentPostingPolicyInput
from modules.procurement.models import Supplier


async def validate_settings(session, org_id, on, settings):
    purchase = settings.purchase
    accounts = await service.accounts_on(session, org_id, on)
    roles = [(code, "inventory") for code in
             [purchase.default_inventory_account, *purchase.inventory_by_sku.values(),
              *purchase.inventory_by_category.values()]]
    roles += [(code, "settlement") for code in
              [purchase.default_settlement_account, *purchase.settlement_by_supplier.values()]]
    roles.append((purchase.vat_account, "vat"))
    for code, role in roles:
        if code is None:
            continue
        account = accounts.get(code)
        roots, category = ({"10", "41"}, "asset") if role == "inventory" else (
            ({"60"}, "liability") if role == "settlement" else ({"18"}, "asset"))
        if (account is None or code.split(".")[0] not in roots
                or account.category != category or account.cash
                or account.quantity_tracking != (role == "inventory")):
            raise service.AccountingError(f"Счёт {code} несовместим с правилом поступления: {role}")
    for model, selectors, active in (
        (Sku, purchase.inventory_by_sku, Sku.is_active),
        (NomenclatureCategory, purchase.inventory_by_category, NomenclatureCategory.is_active),
        (Supplier, purchase.settlement_by_supplier, Supplier.status == "active"),
    ):
        if not selectors:
            continue
        ids = {int(key) for key in selectors}
        found = set((await session.scalars(select(model.id).where(model.id.in_(ids), active))).all())
        if found != ids:
            raise service.AccountingError("Правило содержит отсутствующий или неактивный товар, группу или поставщика")


async def scoped_source(session, org_id, receipt_id, expected_version, gateway):
    source = await gateway.receipt_source(session, org_id, receipt_id)
    if source is None:
        raise HTTPException(404, "Поступление не найдено в выбранной организации")
    if source["organization_id"] != org_id or source["id"] != receipt_id or source["version"] != expected_version:
        raise HTTPException(409, "Версия поступления изменилась. Обновите документ")
    return source


async def resolve_options(session, org_id, source, data):
    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == org_id, Policy.effective_from <= data.posting_date,
    ).order_by(Policy.effective_from.desc()).limit(1))
    if policy is None or policy.document_posting is None:
        raise HTTPException(409, "На выбранную дату не настроены автоматические проводки поступлений")
    settings = DocumentPostingPolicyInput.model_validate(policy.document_posting).purchase
    document = source["document"]
    supplier_id = document.get("supplier_id")
    if type(supplier_id) is not int or supplier_id <= 0:
        raise HTTPException(409, "Для автоматических проводок требуется выбранный поставщик")
    settlement = settings.settlement_by_supplier.get(str(supplier_id), settings.default_settlement_account)
    if settlement is None:
        raise HTTPException(409, "Не настроен счёт расчётов для выбранного поставщика")
    items = document["items"]
    ids = {item.get("sku_id") for item in items}
    if not ids or any(type(key) is not int or key <= 0 for key in ids):
        raise HTTPException(409, "Каждая строка должна быть связана с номенклатурой ERP")
    skus = {sku.id: sku for sku in (await session.scalars(select(Sku).where(
        Sku.id.in_(ids), Sku.is_active.is_(True)).execution_options(populate_existing=True))).all()}
    inventory = []
    for index, item in enumerate(items, 1):
        sku = skus.get(item["sku_id"])
        if sku is None or sku.code != item["sku"]:
            raise HTTPException(409, f"Строка {index}: номенклатура неактивна или изменилась")
        code = settings.inventory_by_sku.get(str(sku.id))
        if code is None and sku.category_id is not None:
            category = await session.get(NomenclatureCategory, sku.category_id, populate_existing=True)
            if category is None or not category.is_active:
                raise HTTPException(409, f"Строка {index}: группа номенклатуры недоступна")
            code = settings.inventory_by_category.get(str(sku.category_id))
        code = code or settings.default_inventory_account
        if code is None:
            raise HTTPException(409, f"Строка {index}: не настроен счёт запасов для товара или группы")
        inventory.append(code)
    has_vat = any(Decimal(str(item["vat_amount"])) != 0 for item in items)
    if has_vat and settings.vat_account is None:
        raise HTTPException(409, "В поступлении есть НДС, но его счёт не настроен")
    return ReceiptAccountingOptions(expected_version=data.expected_version,
        posting_date=data.posting_date, policy_id=policy.id, settlement_account=settlement,
        vat_account=settings.vat_account if has_vat else None, inventory_accounts=inventory)
