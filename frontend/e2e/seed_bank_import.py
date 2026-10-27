"""Seed only the fixed local Playwright database; never accepts a database URL."""
import os
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from modules.accounting.models import (  # noqa: E402
    Account,
    BankAccountMapping,
    Organization,
    Policy,
    SourceBinding,
)
from modules.finance.models import BankTransaction  # noqa: E402

path = ROOT / "e2e.db"
if os.environ.get("AIOS_E2E_SEED") != "1" or not path.is_file() or path.is_symlink():
    raise RuntimeError("Only an existing dedicated e2e.db may be seeded")
org_id = int(sys.argv[1])
engine = create_engine("sqlite:///" + path.as_posix(), execution_options={
    "schema_translate_map": {"accounting": None, "finance": None},
})
with engine.begin() as connection:
    name = connection.scalar(select(Organization.name).where(Organization.id == org_id))
    if not name or not name.startswith("E2E bank dimensions "):
        raise RuntimeError("Only owned synthetic organizations")
    connection.execute(Policy.__table__.insert().values(
        organization_id=org_id, effective_from=date(2026, 1, 1), reference="SYNTHETIC E2E ONLY",
        inventory_method="specific", allocation_basis="direct_cost", depreciation_method="straight_line",
        normative_reference="Synthetic test fixture; not statutory approval", normative_verified=True, approved_by="e2e",
    ))
    for code, title, cash, dimensions in [("51", "Банк", True, ["bank_statement"]), ("62", "Покупатели", False, ["counterparty", "contract"])]:
        connection.execute(Account.__table__.insert().values(
            organization_id=org_id, code=code, title=title, category="asset", cash=cash,
            valid_from=date(2026, 1, 1), required_dimensions=dimensions, currency_tracking=False,
            quantity_tracking=False, normative_ref="SYNTHETIC E2E ONLY",
        ))
    account_id = connection.scalar(select(Account.id).where(Account.organization_id == org_id, Account.code == "51"))
    assert account_id is not None, "Synthetic bank account is required"
    for provider, external_account in (("synthetic-bank", f"main-{org_id}"), ("Synthetic bank", f"SYNTHETIC-ACCOUNT-{org_id}")):
        connection.execute(BankAccountMapping.__table__.insert().values(
            organization_id=org_id, provider=provider, external_account=external_account, currency="BYN",
            valid_from=date(2026, 1, 1), version=1, ledger_account_id=account_id,
            dimensions={"bank_statement": "SYNTHETIC E2E STATEMENT"},
            evidence="SYNTHETIC E2E ONLY", actor="e2e",
        ))
    result = connection.execute(BankTransaction.__table__.insert().values(
        ext_id=f"E2E-BANK-{org_id}", occurred_on=date(2026, 9, 3), amount="120.00", currency="BYN",
        source_provider="synthetic-bank", account_code=f"main-{org_id}", direction="receipt",
        payer_name="Synthetic buyer", purpose="Synthetic advance",
    ))
    connection.execute(SourceBinding.__table__.insert().values(
        organization_id=org_id, source_type="finance_bank_transaction", source_id=result.inserted_primary_key[0],
        ownership="own", evidence="Owned synthetic Playwright fixture", actor="e2e",
    ))
engine.dispose()
