"""Seed only the fixed local Playwright database; never accepts a database URL."""
import json
import os
import sys
from datetime import date
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, func, select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from modules.accounting.models import (  # noqa: E402
    AccessGrant,
    Account,
    Entry,
    Organization,
    Policy,
    SourceBinding,
)
from modules.finance.models import BankTransaction  # noqa: E402


def main():
    path = ROOT / "e2e.db"
    if os.environ.get("AIOS_E2E_SEED") != "1" or not path.is_file() or path.is_symlink():
        raise RuntimeError("Only an existing dedicated e2e.db may be seeded")
    command = json.load(sys.stdin)
    org_id, actor = command["organization_id"], command["actor"]
    if type(org_id) is not int or org_id <= 0:
        raise ValueError("Invalid configured organization")
    if not isinstance(actor, str) or not actor or len(actor) > 200:
        raise ValueError("Invalid test actor")
    engine = create_engine("sqlite:///" + path.as_posix(), execution_options={
        "schema_translate_map": {"accounting": None, "finance": None},
    })
    try:
        with engine.begin() as connection:
            org = connection.execute(select(Organization.__table__).where(Organization.id == org_id)).mappings().one_or_none()
            if not org or org["unp"] != "190000007" or org["name"] != "E2E installation seller":
                raise RuntimeError("Only the configured synthetic organization may be used")
            role = connection.scalar(select(AccessGrant.role).where(
                AccessGrant.organization_id == org_id, AccessGrant.subject == actor,
            ))
            if role != "chief":
                raise RuntimeError("The real fixture actor must already have chief access")
            latest = connection.scalar(select(func.max(Entry.posting_date)).where(Entry.organization_id == org_id))
            effective = date(2026, 1, 1)
            configuration = [(Policy, dict(
                organization_id=org_id, effective_from=effective, reference="SYNTHETIC E2E ONLY",
                inventory_method="specific", allocation_basis="direct_cost", depreciation_method="straight_line",
                normative_reference="Synthetic test fixture; not statutory approval", normative_verified=True,
                approved_by="e2e", financial_closing=None, currency_revaluation=None,
                late_cost_allocation=None, production_costing=None, shipment_documents=None, document_posting=None,
            ))]
            for code, title, cash, dimensions in [("51", "Банк", True, ["bank_statement"]), ("62", "Покупатели", False, ["counterparty", "contract"])]:
                configuration.append((Account, dict(
                    organization_id=org_id, code=code, title=title, category="asset", cash=cash,
                    valid_from=effective, required_dimensions=dimensions, currency_tracking=False,
                    quantity_tracking=False, normative_ref="SYNTHETIC E2E ONLY", catalog_adoption_id=None,
                )))
            for model, expected in configuration:
                query = select(model.__table__).where(model.organization_id == org_id)
                if model is Account:
                    query = query.where(Account.code == expected["code"])
                rows = connection.execute(query).mappings().all()
                if rows:
                    if len(rows) != 1 or any(rows[0][key] != value for key, value in expected.items()):
                        raise RuntimeError("Synthetic configuration differs; refusing to overwrite it")
                else:
                    if latest is not None and effective <= latest:
                        raise RuntimeError("Refusing to insert configuration before posted history")
                    connection.execute(model.__table__.insert().values(**expected))
            ext_id = f"E2E-BANK-{org_id}-{uuid4().hex}"
            result = connection.execute(BankTransaction.__table__.insert().values(
                ext_id=ext_id, occurred_on=date(2026, 9, 3), amount="120.00", currency="BYN",
                payer_name="Synthetic buyer", purpose="Synthetic advance", direction="receipt",
                source_provider="Synthetic bank", account_code="SYNTHETIC-ACCOUNT", source_external_id=ext_id,
            ))
            connection.execute(SourceBinding.__table__.insert().values(
                organization_id=org_id, source_type="finance_bank_transaction", source_id=result.inserted_primary_key[0],
                ownership="own", evidence="Owned synthetic Playwright fixture", actor=actor,
            ))
        print(json.dumps({"organization_id": org_id, "ext_id": ext_id}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
