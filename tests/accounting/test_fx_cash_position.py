from datetime import date
from decimal import Decimal

import pytest

from modules.accounting import fx_cash_position, service
from modules.accounting.models import Account, Organization, Policy
from modules.accounting.schemas import LineInput, PostingInput
from tests.accounting.test_fx_revaluation import _foreign_posting, _policy


async def post_cash_foreign(db, book, *, source="cash-foreign", on=date(2026, 9, 10)):
    policy = await _policy(db, book[0])
    posting = _foreign_posting(policy, source=source)
    posting.document_date = posting.operation_date = posting.posting_date = on
    for line in posting.lines:
        line.rate_date = on
    posting.lines[0].account = "51"
    posting.lines[0].cash_activity = "operating"
    await service.post(db, book[0], posting, "tester")
    await db.commit()
    return policy


async def test_cash_position_uses_only_own_ledger_before_cutoff_and_keeps_basis(db, book):
    await post_cash_foreign(db, book)
    other = Organization(name="Other synthetic company", unp="888888888")
    db.add(other)
    await db.flush()
    other_policy = Policy(organization_id=other.id, effective_from=date(2026, 1, 1),
                          reference="Other synthetic policy", inventory_method="specific",
                          allocation_basis="direct_cost", depreciation_method="straight_line",
                          normative_reference="Synthetic", normative_verified=True, approved_by="tester")
    db.add_all([other_policy,
        Account(organization_id=other.id, code="51", title="Other cash", category="asset",
                valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=True,
                quantity_tracking=False, cash=True, normative_ref="Synthetic"),
        Account(organization_id=other.id, code="60", title="Other payable", category="liability",
                valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=True,
                quantity_tracking=False, cash=False, normative_ref="Synthetic"),
    ])
    await db.commit()
    other_posting = _foreign_posting(other_policy.id, source="other-cash")
    other_posting.document_date = other_posting.operation_date = other_posting.posting_date = date(2026, 9, 9)
    for line in other_posting.lines:
        line.rate_date = date(2026, 9, 9)
    other_posting.lines[0].account = "51"
    other_posting.lines[0].cash_activity = "operating"
    await service.post(db, other.id, other_posting, "tester")
    await db.commit()
    before = await fx_cash_position.position(db, book[0], as_of=date(2026, 9, 9),
                                             account_code="51", dimensions={}, currency="USD")
    result = await fx_cash_position.position(db, book[0], as_of=date(2026, 9, 10),
                                             account_code="51", dimensions={}, currency="USD")
    assert (before["original_balance"], before["book_balance"], before["basis"]["source_lines"]) == ("0", "0", [])
    assert (Decimal(result["original_balance"]), Decimal(result["book_balance"])) == (Decimal("100"), Decimal("300"))
    assert result["posting_available"] is False
    assert result["basis"]["account_versions"][0]["code"] == "51"
    assert len(result["basis"]["source_lines"]) == 1


async def test_cash_position_requires_exact_effective_cash_analytics_and_account(db, book):
    await post_cash_foreign(db, book)
    with pytest.raises(service.AccountingError, match="exact analytics"):
        await fx_cash_position.position(db, book[0], as_of=date(2026, 9, 10),
                                        account_code="51", dimensions={"contract": "C-1"}, currency="USD")
    with pytest.raises(service.AccountingError, match="cash currency-tracked asset"):
        await fx_cash_position.position(db, book[0], as_of=date(2026, 9, 10),
                                        account_code="62", dimensions={}, currency="USD")
    with pytest.raises(service.AccountingError, match="unknown or inactive"):
        await fx_cash_position.position(db, book[0], as_of=date(2026, 9, 10),
                                        account_code="51", dimensions={}, currency="ZZZ")


async def test_cash_position_blocks_unattributed_byn_movement(db, book):
    policy = await post_cash_foreign(db, book)
    ambiguous = PostingInput(
        source="cash-byn-movement", source_version=1, operation="manual",
        document_date=date(2026, 9, 30), operation_date=date(2026, 9, 30),
        posting_date=date(2026, 9, 30), policy_id=policy, rule_version="synthetic-v1",
        explanation="Synthetic unsupported BYN cash movement", lines=[
            LineInput(account="51", side="debit", amount="20.00", cash_activity="operating"),
            LineInput(account="60", side="credit", amount="20.00"),
        ],
    )
    await service.post(db, book[0], ambiguous, "tester")
    await db.commit()
    with pytest.raises(service.AccountingError, match="unsupported BYN movement"):
        await fx_cash_position.position(db, book[0], as_of=date(2026, 9, 30),
                                        account_code="51", dimensions={}, currency="USD")
