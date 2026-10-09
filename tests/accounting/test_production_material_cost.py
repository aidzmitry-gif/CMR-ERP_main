from datetime import date
from decimal import Decimal

import pytest

from modules.accounting import inventory_issues, production_material_cost
from modules.accounting.models import Policy
from modules.accounting.service import AccountingError
from modules.wms.models import StockMovement
from modules.wms.production_material_issues import ProductionMaterialIssue


class Session:
    def __init__(self, *values):
        self.values = list(values)

    async def scalar(self, _statement):
        return self.values.pop(0)


class Production:
    async def cost_orders(self, _session, _org, _order_ids):
        return [{"order_id": 42, "product": "Widget", "quantity": 2}]


def policy(material_account=None):
    return Policy(id=7, organization_id=11, effective_from=date(2026, 10, 1),
                  reference="Reviewed production policy", production_costing={
                      "overhead_accounts": ["25"], "wip_account": "20",
                      "pool_dimensions": ["department"], "order_dimension": "order",
                      "rounding": "largest_remainder_cent", "reference": "Reviewed production policy",
                      **({"material_inventory_account": material_account} if material_account else {}),
                  })


def command(**changes):
    value = {
        "policy_id": 7, "order_id": 42, "order_analytics": "A", "department": "SHOP",
        "wms_movement_id": 9, "posting_date": "2026-10-10", "account": "10.1",
        "warehouse": "Main", "sku": "MAT-1", "lot": "LOT-1", "quantity": "2.00",
    }
    value.update(changes)
    return production_material_cost.ProductionMaterialIssuePreviewInput.model_validate(value)


def movement(**changes):
    value = {"id": 9, "organization_id": 11, "kind": "out", "reason": "production_issue",
             "sku_code": "MAT-1", "warehouse": "Main", "batch_ref": "LOT-1", "qty": Decimal("2.00"),
             "doc_ref": "production_material:00000000-0000-0000-0000-000000000001"}
    value.update(changes)
    return StockMovement(**value)


def binding(move):
    return ProductionMaterialIssue(
        id=3, organization_id=11, order_id=42, movement_id=9,
        request_key="00000000-0000-0000-0000-000000000001",
        operation_date=date(2026, 10, 10), actor="tester",
        snapshot={
            "command": {"request_id": "00000000-0000-0000-0000-000000000001",
                        "order_id": 42, "expected_order_digest": "a" * 64,
                        "operation_date": "2026-10-10", "sku_code": move.sku_code,
                        "quantity": "2.00", "warehouse": move.warehouse,
                        "location_id": move.location_id, "lot": move.batch_ref,
                        "evidence": "Synthetic material issue"},
            "order_snapshot": {},
            "movement": {"id": move.id, "organization_id": move.organization_id,
                         "sku_code": move.sku_code, "warehouse": move.warehouse,
                         "kind": move.kind, "qty": "2.00", "reason": move.reason,
                         "location_id": move.location_id, "lot": move.batch_ref,
                         "doc_ref": move.doc_ref},
        },
    )


async def prepare(monkeypatch, *, move=None, material_account=None, **changes):
    async def unlock(*_args):
        return None
    async def valid(*_args):
        return {}
    async def cost(*_args, **_kwargs):
        return {"account": _args[2].account, "issue_cost_byn": "12.50", "inventory_dimensions": {"warehouse": "Main", "sku": "MAT-1", "lot": "LOT-1"},
                "book_quantity": "5.000000", "book_value_byn": "31.25", "basis_digest": "a" * 64}
    monkeypatch.setattr(production_material_cost, "lock_organization", unlock)
    monkeypatch.setattr(production_material_cost, "validate_accounts", valid)
    monkeypatch.setattr(production_material_cost.inventory_cost, "preview_issue", cost)
    physical = move or movement()
    return await production_material_cost.preview_material_issue(
        Session(policy(material_account), binding(physical), physical), 11, "2026-10", command(**changes), Production())


@pytest.mark.asyncio
@pytest.mark.parametrize("configured,explicit,expected", [("10.1", None, "10.1"), ("41.01", None, "41.01"), ("41.01", "10.1", "10.1")])
async def test_material_automatic_accounts_use_policy_without_replacing_manual_selection(monkeypatch, configured, explicit, expected):
    result = await prepare(monkeypatch, material_account=configured, account=explicit)
    assert result["inventory_cost"]["account"] == expected
    assert result["candidate_posting"]["credit"]["account"] == expected
    assert result["candidate_posting"]["debit"]["account"] == "20"
    assert result["candidate_posting"]["debit"]["amount_byn"] == "12.50"


@pytest.mark.asyncio
async def test_material_missing_automatic_rule_holds_instead_of_guessing(monkeypatch):
    with pytest.raises(AccountingError, match="Configure a material inventory account"):
        await prepare(monkeypatch, account=None)


def test_material_confirmation_requires_a_frozen_account():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        production_material_cost.ProductionMaterialIssuePostingConfirmInput.model_validate({
            **command(account=None).model_dump(mode="json"), "basis_digest": "a" * 64, "digest": "b" * 64,
        })


@pytest.mark.asyncio
async def test_material_issue_joins_exact_wms_movement_and_lot_cost(monkeypatch):
    result = await prepare(monkeypatch)
    assert result["status"] == "reviewed_material_cost"
    assert result["wms_movement"]["reason"] == "production_issue"
    assert result["inventory_cost"]["issue_cost_byn"] == "12.50"
    assert result["candidate_posting"] == {
        "debit": {"account": "20", "side": "debit", "amount_byn": "12.50", "dimensions": {"department": "SHOP", "order": "A"}},
        "credit": {"account": "10.1", "side": "credit", "amount_byn": "12.50",
                   "dimensions": {"warehouse": "Main", "sku": "MAT-1", "lot": "LOT-1"}, "quantity": "2.000000"},
    }
    assert result["posting_available"] is False and result["final_cost_certified"] is False


@pytest.mark.asyncio
async def test_sales_or_generic_out_movement_cannot_be_used_as_material_issue(monkeypatch):
    with pytest.raises(AccountingError, match="exact production material issue"):
        await prepare(monkeypatch, move=movement(reason="pick"))


@pytest.mark.asyncio
async def test_raw_wms_movement_without_immutable_source_binding_is_rejected(monkeypatch):
    async def unlock(*_args):
        return None
    async def valid(*_args):
        return {}
    monkeypatch.setattr(production_material_cost, "lock_organization", unlock)
    monkeypatch.setattr(production_material_cost, "validate_accounts", valid)
    with pytest.raises(AccountingError, match="source binding is required"):
        await production_material_cost.preview_material_issue(
            Session(policy(), None), 11, "2026-10", command(), Production())


@pytest.mark.asyncio
async def test_generic_inventory_issue_workflow_cannot_admit_production_source():
    from modules.accounting.schemas import InventoryIssueDocument

    document = InventoryIssueDocument(
        source="production:material:11:00000000-0000-0000-0000-000000000001", source_version=1,
        document_date="2026-10-10", operation_date="2026-10-10", posting_date="2026-10-10",
        policy_id=7, account="10.1", warehouse="Main", sku="MAT-1", lot="LOT-1", quantity="1.00",
        expense_account="20", expense_dimensions={"department": "SHOP", "order": "A"},
        explanation="Reviewed production material issue",
    )
    with pytest.raises(AccountingError, match="reviewed production workflow"):
        await inventory_issues.prepare(Session(), 11, document)


@pytest.mark.asyncio
async def test_material_issue_date_must_be_in_selected_period(monkeypatch):
    with pytest.raises(AccountingError, match="selected period"):
        await prepare(monkeypatch, posting_date="2026-09-30")


@pytest.mark.asyncio
async def test_material_preview_endpoint_is_private_and_scoped(client, book, monkeypatch):
    async def fake_preview(*_args, **_kwargs):
        return {"organization_id": book[0], "month": "2026-10", "scope": "production_material_cost_basis"}

    monkeypatch.setattr(production_material_cost, "preview_material_issue", fake_preview)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/production-material-issue-preview",
        json=command(policy_id=book[1]).model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["organization_id"] == book[0]


@pytest.mark.asyncio
async def test_material_posting_preview_endpoint_exposes_candidate_without_certifying_cost(client, book, monkeypatch):
    async def fake_prepare(*_args, **_kwargs):
        return {"organization_id": book[0], "month": "2026-10", "scope": "production_material_cost_basis",
                "posting_available": True, "final_cost_certified": False,
                "basis_digest": "a" * 64, "digest": "b" * 64}

    monkeypatch.setattr(production_material_cost, "prepare_material_issue_posting", fake_prepare)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/production-material-issue-posting-preview",
        json=command(policy_id=book[1]).model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert response.json()["posting_available"] is True
    assert response.json()["final_cost_certified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("automatic", [False, True])
async def test_material_posting_preview_binds_generic_issue_to_reviewed_source(monkeypatch, automatic):
    from modules.accounting.schemas import PostingInput, ProductionCostPolicyInput

    physical = movement()
    source = binding(physical)
    settings = ProductionCostPolicyInput.model_validate({
        "overhead_accounts": ["25"], "wip_account": "20", "pool_dimensions": ["department"],
        "order_dimension": "order", "rounding": "largest_remainder_cent", "reference": "Reviewed production policy",
        "material_inventory_account": "10.1",
    })
    review = {"organization_id": 11, "month": "2026-10", "policy_id": 7,
              "inventory_cost": {"basis_digest": "a" * 64, "issue_cost_byn": "12.50", "account": "10.1"}}
    posted = PostingInput.model_validate({
        "source": "production:material:11:00000000-0000-0000-0000-000000000001", "source_version": 1,
        "operation": "inventory_issue", "document_date": "2026-10-10", "operation_date": "2026-10-10",
        "posting_date": "2026-10-10", "policy_id": 7, "rule_version": "specific-issue-v1:test",
        "explanation": "Reviewed material", "lines": [
            {"account": "20", "side": "debit", "amount": "12.50", "dimensions": {"department": "SHOP", "order": "A"}},
            {"account": "10.1", "side": "credit", "amount": "12.50", "quantity": "2.000000",
             "dimensions": {"warehouse": "Main", "sku": "MAT-1", "lot": "LOT-1"}},
        ],
    })

    async def fake_preview(*_args, **_kwargs):
        return review
    async def fake_policy(*_args, **_kwargs):
        return date(2026, 10, 1), date(2026, 10, 31), policy(), settings
    async def fake_source(*_args, **_kwargs):
        return date(2026, 10, 1), date(2026, 10, 31), source, physical
    async def fake_prepare(_session, _org, document, **kwargs):
        assert kwargs["allow_production_material"] is True
        assert document.source == "production:material:11:00000000-0000-0000-0000-000000000001"
        assert document.account == "10.1"
        return {"basis_digest": "a" * 64}, posted

    monkeypatch.setattr(production_material_cost, "preview_material_issue", fake_preview)
    monkeypatch.setattr(production_material_cost, "_load_policy", fake_policy)
    monkeypatch.setattr(production_material_cost, "_load_source", fake_source)
    monkeypatch.setattr(production_material_cost.inventory_issues, "prepare", fake_prepare)
    data = production_material_cost.ProductionMaterialIssuePostingInput.model_validate(command(account=None if automatic else "10.1").model_dump(mode="json"))
    result = await production_material_cost.prepare_material_issue_posting(None, 11, "2026-10", data, Production())
    assert result["posting_available"] is True and result["final_cost_certified"] is False
    assert result["digest"] == production_material_cost.service.digest(posted)
    assert result["posting_document"]["account"] == "10.1"


@pytest.mark.asyncio
async def test_material_issue_confirmation_uses_reserved_source_workflow(monkeypatch):
    from modules.accounting.schemas import ProductionCostPolicyInput

    physical = movement()
    source = binding(physical)
    settings = ProductionCostPolicyInput.model_validate({
        "overhead_accounts": ["25"], "wip_account": "20", "pool_dimensions": ["department"],
        "order_dimension": "order", "rounding": "largest_remainder_cent", "reference": "Reviewed production policy",
    })
    async def fake_policy(*_args, **_kwargs):
        assert _kwargs["current"] is False
        return date(2026, 10, 1), date(2026, 10, 31), policy(), settings
    async def fake_source(*_args, **_kwargs):
        return date(2026, 10, 1), date(2026, 10, 31), source, physical
    async def fake_confirm(_session, _org, document, _basis, _digest, _actor, _event_bus, **kwargs):
        assert kwargs["allow_production_material"] is True
        assert document.source.startswith("production:material:11:")
        assert document.account == "10.1"
        return "posted-entry"

    monkeypatch.setattr(production_material_cost, "_load_policy", fake_policy)
    monkeypatch.setattr(production_material_cost, "_load_source", fake_source)
    monkeypatch.setattr(production_material_cost.inventory_issues, "confirm", fake_confirm)
    base = command()
    data = production_material_cost.ProductionMaterialIssuePostingConfirmInput.model_validate({
        **base.model_dump(mode="json"), "basis_digest": "a" * 64, "digest": "b" * 64,
    })
    assert await production_material_cost.confirm_material_issue_posting(
        None, 11, "2026-10", data, "tester") == "posted-entry"


@pytest.mark.asyncio
async def test_automatic_zero_prepare_freezes_account_and_replay_uses_original_policy(monkeypatch):
    from types import SimpleNamespace

    from modules.accounting import zero_value_disposals
    from modules.accounting.schemas import ProductionCostPolicyInput

    original = policy("10.1")
    original.inventory_method = "weighted_average"
    settings = ProductionCostPolicyInput.model_validate(original.production_costing)
    physical = movement()
    source = binding(physical)
    review = {"inventory_cost": {"account": "10.1", "issue_cost_byn": "0.00", "basis_digest": "a" * 64,
        "inventory_layers": [{"source_entry_id": 21, "source_line_id": 31, "quantity": "2.000000",
            "dimensions": {"warehouse": "Main", "sku": "MAT-1", "lot": "LOT-1"}}]}}

    class PgSession(Session):
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        async def scalar(self, statement, _parameters=None):
            return await super().scalar(statement)

    async def fake_review(*_args, **_kwargs):
        return review

    async def fake_policy(*_args, **kwargs):
        assert kwargs["current"] is True
        return None, None, original, settings

    async def fake_source(*_args, **_kwargs):
        return None, None, source, physical

    monkeypatch.setattr(production_material_cost, "preview_material_issue", fake_review)
    monkeypatch.setattr(production_material_cost, "_load_policy", fake_policy)
    monkeypatch.setattr(production_material_cost, "_load_source", fake_source)
    request = production_material_cost.ProductionMaterialIssuePostingInput.model_validate(command(account=None).model_dump())
    prepared = await production_material_cost.prepare_material_zero_issue(
        PgSession(True, 5, "d" * 64), 11, "2026-10", request, Production())
    frozen = prepared["zero_value_receipt"]
    assert frozen["document"]["account"] == "10.1"
    assert frozen["destination_account"] == "20"
    assert frozen["inventory_layers"][0]["inventory_account"] == "10.1"
    assert prepared["basis_digest"] == "d" * 64 != review["inventory_cost"]["basis_digest"]

    async def saved_policy(*_args, **kwargs):
        # No latest policy/default lookup, even if today's rule would choose 41.
        assert kwargs["current"] is False
        return None, None, original, settings

    async def no_prepare(*_args, **_kwargs):
        raise AssertionError("A confirmed retry must not re-prepare or re-cost")

    saved = SimpleNamespace(command=frozen, id=17, organization_id=11, actor="tester",
                            basis_digest="d" * 64, digest="e" * 64)

    async def unlock(*_args):
        return None

    async def register(_session, _org, _actor, canonical, **_kwargs):
        assert canonical.model_dump(mode="json") == frozen
        return saved

    monkeypatch.setattr(production_material_cost, "lock_organization", unlock)
    monkeypatch.setattr(production_material_cost, "_load_policy", saved_policy)
    monkeypatch.setattr(production_material_cost, "prepare_material_zero_issue", no_prepare)
    monkeypatch.setattr(production_material_cost, "preview_material_issue", no_prepare)
    monkeypatch.setattr(production_material_cost.inventory_cost, "preview_issue", no_prepare)
    monkeypatch.setattr(zero_value_disposals, "register_standalone_zero_value_issue", register)
    confirm = production_material_cost.ProductionMaterialIssuePostingConfirmInput.model_validate({
        **command().model_dump(), "basis_digest": prepared["basis_digest"], "digest": prepared["digest"], "zero_value": True,
    })
    outcome = await production_material_cost.confirm_material_zero_issue(
        Session(saved), 11, "2026-10", confirm, "tester", Production())
    assert outcome["quantity_registered"] is True and outcome["entry_id"] is None
