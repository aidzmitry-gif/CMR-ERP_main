"""Synthetic controls for reconciliation identity, amounts and duplicate preservation."""
from decimal import Decimal

from modules.finance.models import Payment
from modules.finance.reconcile import reconcile_with_onec


async def test_reconcile_does_not_guess_between_multiple_unmatched_duplicates(session):
    session.add_all([
        Payment(ref="synthetic", amount=Decimal("1.00"), kind="receivable", status="pending"),
        Payment(ref="synthetic", amount=Decimal("2.00"), kind="receivable", status="pending"),
    ])
    await session.commit()

    class Gateway:
        async def fetch_payments(self):
            return [{"ref": "synthetic", "amount": "3.00"}, {"ref": "synthetic", "amount": "4.00"}]

    result = await reconcile_with_onec(session, Gateway())
    assert result["matched"] == result["amount_mismatch"] == []
    assert [row["amount"] for row in result["only_in_erp"]] == ["1.00", "2.00"]
    assert [row["amount"] for row in result["only_in_1c"]] == ["3.00", "4.00"]


async def test_reconcile_rejects_invalid_amounts_and_identity_collisions(session):
    session.add(Payment(ref="a|b", counterparty_ref="c", amount=Decimal("0.00"),
                        kind="receivable", status="pending"))
    await session.commit()

    class Gateway:
        async def fetch_payments(self):
            return [{"ref": "a", "counterparty_ref": "b|c", "amount": "0.00"},
                    {"ref": "a|b", "counterparty_ref": "c", "amount": "0.001"},
                    {"ref": "a|b", "counterparty_ref": "c", "amount": "Infinity"},
                    {"ref": "a|b", "counterparty_ref": "c", "amount": None},
                    {"ref": "a|b", "counterparty_ref": "c", "amount": True},
                    {"ref": "", "amount": "0.00"}]

    result = await reconcile_with_onec(session, Gateway())
    assert result["matched"] == result["amount_mismatch"] == []
    assert [row["amount"] for row in result["only_in_erp"]] == ["0.00"]
    assert [row["amount"] for row in result["only_in_1c"]] == ["0.00"]
    assert [row["reason"] for row in result["invalid_source_rows"]] == [
        "invalid_amount", "invalid_amount", "invalid_amount", "invalid_amount", "invalid_identity",
    ]


async def test_reconcile_endpoint_discloses_mismatch_and_invalid_rows(api, session, monkeypatch):
    session.add_all([
        Payment(ref="synthetic-exact", amount=Decimal("10.00"), kind="receivable", status="pending"),
        Payment(ref="synthetic-diff", amount=Decimal("20.00"), kind="receivable", status="pending"),
    ])
    await session.commit()

    class Gateway:
        async def fetch_payments(self):
            return [{"ref": "synthetic-exact", "amount": "10,00"},
                    {"ref": "synthetic-diff", "amount": "21.00"},
                    {"ref": "synthetic-invalid", "amount": "NaN"}]

    monkeypatch.setattr(api._transport.app.state.core.services, "onec", Gateway())
    response = await api.get("/finance/reconcile-1c")
    assert response.status_code == 200
    result = response.json()
    assert result["source_available"] is True
    assert result["matched"] == [{"ref": "synthetic-exact", "amount": "10.00", "counterparty_ref": None}]
    assert result["amount_mismatch"] == [{"ref": "synthetic-diff", "counterparty_ref": None,
                                          "erp_amount": "20.00", "one_c_amount": "21.00"}]
    assert result["invalid_source_rows"] == [{"ref": "synthetic-invalid", "counterparty_ref": None,
                                              "reason": "invalid_amount"}]
    assert result["only_in_erp"] == result["only_in_1c"] == []
