"""Seed only the fixed local Playwright database; never accepts a database URL."""
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from modules.accounting.models import Account, Organization, Policy, SourceBinding  # noqa: E402
from modules.finance.models import BankTransaction  # noqa: E402

path = ROOT / "e2e.db"
assert path.is_file(), "Playwright database must already exist"
org_id = int(sys.argv[1])
engine = create_engine("sqlite:///" + path.as_posix(), execution_options={
    "schema_translate_map": {"accounting": None, "finance": None},
})
with engine.begin() as connection:
    name = connection.scalar(select(Organization.name).where(Organization.id == org_id))
    assert name and name.startswith("E2E bank dimensions "), "Only owned synthetic organizations"
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
    result = connection.execute(BankTransaction.__table__.insert().values(
        ext_id=f"E2E-BANK-{org_id}", occurred_on=date(2026, 9, 3), amount="120.00", currency="BYN",
        payer_name="Synthetic buyer", purpose="Synthetic advance",
    ))
    connection.execute(SourceBinding.__table__.insert().values(
        organization_id=org_id, source_type="finance_bank_transaction", source_id=result.inserted_primary_key[0],
        ownership="own", evidence="Owned synthetic Playwright fixture", actor="e2e",
    ))
engine.dispose()
