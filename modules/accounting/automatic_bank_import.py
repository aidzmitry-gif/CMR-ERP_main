"""Resolve configured bank operation accounts, retaining the canonical bank owner."""
from datetime import date

from pydantic import Field, field_validator
from sqlalchemy import select

from modules.accounting import bank_account_mapping, bank_import, service
from modules.accounting.models import BankImportReceipt, Policy
from modules.accounting.schemas import (
    BankOperationKey,
    BankPostingPolicyInput,
    DocumentPostingPolicyInput,
    Input,
)


class BankAutomaticInput(Input):
    request_key: str = Field(min_length=36, max_length=36)
    source_transaction_id: int = Field(gt=0, strict=True)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_id: int = Field(gt=0, strict=True)
    posting_date: date
    rule_key: BankOperationKey
    settlement_dimensions: dict[str, str] = Field(default_factory=dict)
    explanation: str = Field(min_length=1, max_length=700)

    @field_validator("request_key")
    @classmethod
    def canonical_key(cls, value):
        return bank_import._uuid(value)


class BankAutomaticConfirmation(Input):
    rule_key: BankOperationKey
    command: bank_import.BankImportConfirmInput


async def validate_settings(session, org_id, on, settings: BankPostingPolicyInput):
    accounts = await service.accounts_on(session, org_id, on)
    for rule in settings.rules.values():
        account = accounts.get(rule.settlement_account)
        if (account is None or account.category not in {"asset", "liability"}
                or account.cash or account.quantity_tracking):
            raise service.AccountingError("Правило банковской операции требует действующий неденежный счёт расчётов без количественного учёта")


async def effective_settings(session, org_id, on):
    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == org_id, Policy.effective_from <= on,
    ).order_by(Policy.effective_from.desc()).limit(1))
    if policy is None or policy.document_posting is None:
        raise service.AccountingError("На выбранную дату не настроены автоматические проводки банка")
    settings = DocumentPostingPolicyInput.model_validate(policy.document_posting).bank
    if settings is None:
        raise service.AccountingError("На выбранную дату не настроены автоматические проводки банка")
    await validate_settings(session, org_id, on, settings)
    return policy, settings


async def options(session, org_id, on):
    policy, settings = await effective_settings(session, org_id, on)
    accounts = await service.accounts_on(session, org_id, on)
    return {"organization_id": org_id, "policy_id": policy.id, "rules": [
        {"key": key, **rule.model_dump(),
         "required_dimensions": accounts[rule.settlement_account].required_dimensions}
        for key, rule in settings.rules.items()
    ]}


async def resolve_command(session, org_id, data: BankAutomaticInput):
    await service.lock_organization(session, org_id)
    row, source, digest = await bank_import._source(session, org_id, data.source_transaction_id)
    if digest != data.source_digest:
        raise service.AccountingError("Банковская строка изменилась. Обновите исходный документ")
    policy, settings = await effective_settings(session, org_id, data.posting_date)
    if policy.id != data.policy_id:
        raise service.AccountingError("Учётная политика изменилась. Повторите расчёт")
    rule = settings.rules.get(data.rule_key)
    if rule is None:
        raise service.AccountingError("Для выбранной операции не настроены счета")
    # Never interpret payer/purpose or legacy absence as a transaction direction.
    if source.get("direction") != rule.direction:
        raise service.AccountingError("Направление банковской строки не соответствует выбранной операции")
    mapping = await bank_account_mapping.resolve_fingerprint(session, org_id,
        provider=row.source_provider, external_account=row.account_code,
        currency=row.currency, on=row.occurred_on)
    return bank_import.BankImportInput(**data.model_dump(exclude={"rule_key"}),
        bank_account=mapping["bank_account"], bank_dimensions=mapping["dimensions"],
        settlement_account=rule.settlement_account, cash_activity=rule.cash_activity)


async def prepare(session, org_id, data):
    command = await resolve_command(session, org_id, data)
    result = await bank_import.prepare(session, org_id, command)
    return {**result, "resolved_command": command.model_dump(mode="json"), "rule_key": data.rule_key}


async def confirm(session, org_id, data, actor, event_bus=None):
    await service.lock_organization(session, org_id)
    saved = await session.scalar(select(BankImportReceipt).where(
        BankImportReceipt.organization_id == org_id,
        BankImportReceipt.source_transaction_id == data.command.source_transaction_id,
    ).with_for_update())
    if saved is None:
        body = bank_import._command_body(data.command)
        resolved = await resolve_command(session, org_id, BankAutomaticInput.model_validate({
            **{key: value for key, value in body.items()
               if key not in {"bank_account", "bank_dimensions", "settlement_account", "cash_activity"}},
            "rule_key": data.rule_key,
        }))
        if bank_import._command_body(resolved) != body:
            raise service.AccountingError("Правила банковских проводок изменились. Повторите расчёт")
    # The owner authenticates the saved command/digests before current source reads.
    return await bank_import.confirm(session, org_id, data.command, actor, event_bus)
