from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.accounting import production_output_cost, production_output_transfer
from modules.accounting.models import Policy


class Session:
    def __init__(self, *values):
        self.values = list(values)
        self.added = []

    async def scalar(self, _statement):
        return self.values.pop(0)

    async def get(self, _model, _key):
        return None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


def policy():
    return Policy(
        id=7,
        organization_id=11,
        effective_from=date(2026, 10, 1),
        reference="Reviewed production policy",
        production_costing={
            "overhead_accounts": ["25"],
            "wip_account": "20",
            "finished_goods_account": "43",
            "pool_dimensions": ["department"],
            "order_dimension": "order",
            "rounding": "largest_remainder_cent",
            "reference": "Reviewed production policy",
        },
    )


def command(**changes):
    value = {
        "policy_id": 7,
        "order_id": 42,
        "analytical_order": "A",
        "department": "SHOP",
        "warehouse": "Main",
        "posting_date": "2026-10-31",
        "output_document_ids": [101],
    }
    value.update(changes)
    return production_output_transfer.ProductionOutputTransferInput.model_validate(value)


def review():
    return {
        "organization_id": 11,
        "month": "2026-10",
        "policy_id": 7,
        "basis_digest": "a" * 64,
        "status": "ready_for_transfer_review",
        "candidate_transfer_byn": "100.00",
        "output": {
            "planned_quantity": "2.00",
            "confirmed_quantity": "2.00",
            "accepted_quantity": "2.00",
            "rejected_quantity": "0.00",
            "pending_quantity": "0.00",
            "sku_code": "WIDGET",
            "lot": "LOT-1",
            "documents": [{"document_id": 101, "operation_date": "2026-10-10"}],
        },
        "target": {"finished_goods_account": "43"},
        "wip": {
            "account": "20",
            "groups": [
                {
                    "dimensions": {"department": "SHOP", "order": "A"},
                    "balance_byn": "100.00",
                    "source_lines": [],
                },
            ],
        },
    }


@pytest.mark.asyncio
async def test_prepare_builds_explicit_finished_goods_transfer(monkeypatch):
    async def fake_preview(*_args, **_kwargs):
        return review()

    async def fake_accounts(*_args, **_kwargs):
        class Account:
            def __init__(self, dimensions):
                self.required_dimensions = dimensions

        return {"43": Account({"warehouse", "sku", "lot"}), "20": Account({"department", "order"})}

    async def fake_validate(*_args, **_kwargs):
        return None

    monkeypatch.setattr(production_output_transfer, "preview_output_cost_basis", fake_preview)
    monkeypatch.setattr(production_output_transfer, "validate_accounts", fake_accounts)
    monkeypatch.setattr(production_output_transfer.service, "validate_posting", fake_validate)
    result = await production_output_transfer.prepare_output_transfer(
        Session(policy()), 11, "2026-10", command(), object(), object()
    )
    assert result["posting_available"] is True and result["final_cost_certified"] is False
    posting = result["posting_document"]
    assert posting["operation"] == "production_output_transfer"
    assert posting["lines"] == [
        {
            "account": "43",
            "side": "debit",
            "amount": "100.00",
            "dimensions": {"warehouse": "Main", "sku": "WIDGET", "lot": "LOT-1"},
            "currency": "BYN",
            "original_amount": None,
            "rate": None,
            "rate_scale": None,
            "rate_date": None,
            "rate_source": None,
            "quantity": "2.00",
            "cash_activity": None,
        },
        {
            "account": "20",
            "side": "credit",
            "amount": "100.00",
            "dimensions": {"department": "SHOP", "order": "A"},
            "currency": "BYN",
            "original_amount": None,
            "rate": None,
            "rate_scale": None,
            "rate_date": None,
            "rate_source": None,
            "quantity": None,
            "cash_activity": None,
        },
    ]


@pytest.mark.asyncio
async def test_prepare_preserves_each_positive_wip_analytic_group(monkeypatch):
    async def fake_preview(*_args, **_kwargs):
        value = review()
        value["wip"]["groups"] = [
            {
                "dimensions": {"department": "SHOP-A", "order": "A"},
                "balance_byn": "70.00",
                "source_lines": [],
            },
            {
                "dimensions": {"department": "SHOP-B", "order": "A"},
                "balance_byn": "30.00",
                "source_lines": [],
            },
        ]
        return value

    async def fake_accounts(*_args, **_kwargs):
        class Account:
            def __init__(self, dimensions):
                self.required_dimensions = dimensions

        return {"43": Account({"warehouse", "sku", "lot"}), "20": Account({"department", "order"})}

    async def fake_validate(*_args, **_kwargs):
        return None

    monkeypatch.setattr(production_output_transfer, "preview_output_cost_basis", fake_preview)
    monkeypatch.setattr(production_output_transfer, "validate_accounts", fake_accounts)
    monkeypatch.setattr(production_output_transfer.service, "validate_posting", fake_validate)
    posting = (
        await production_output_transfer.prepare_output_transfer(
            Session(policy()), 11, "2026-10", command(department="TARGET"), object(), object()
        )
    )["posting_document"]
    assert posting["lines"][-2:] == [
        {
            "account": "20",
            "side": "credit",
            "amount": "70.00",
            "dimensions": {"department": "SHOP-A", "order": "A"},
            "currency": "BYN",
            "original_amount": None,
            "rate": None,
            "rate_scale": None,
            "rate_date": None,
            "rate_source": None,
            "quantity": None,
            "cash_activity": None,
        },
        {
            "account": "20",
            "side": "credit",
            "amount": "30.00",
            "dimensions": {"department": "SHOP-B", "order": "A"},
            "currency": "BYN",
            "original_amount": None,
            "rate": None,
            "rate_scale": None,
            "rate_date": None,
            "rate_source": None,
            "quantity": None,
            "cash_activity": None,
        },
    ]


@pytest.mark.asyncio
async def test_real_basis_to_posting_preserves_wip_departments_and_excludes_another_order(
    monkeypatch,
):
    class BasisSession:
        async def scalar(self, _statement):
            return policy()

    class Production:
        async def cost_orders(self, _session, _org, _order_ids):
            return [{"order_id": 42, "product": "Widget", "quantity": "2.00"}]

        async def output_reconciliation(self, _session, _org, _order_id, _warehouse):
            return {
                "planned_quantity": "2.00",
                "confirmed_quantity": "2.00",
                "accepted_quantity": "2.00",
                "rejected_quantity": "0.00",
                "pending_quantity": "0.00",
                "sku_code": "WIDGET",
                "lot": "LOT-1",
                "documents": [{"document_id": 101, "operation_date": "2026-10-10"}],
            }

    source = {
        "snapshot": {
            "lines": [
                {
                    "entry_id": 1,
                    "line_id": 1,
                    "source": "wip-a",
                    "account": "20",
                    "posting_date": "2026-10-10",
                    "side": "debit",
                    "amount_byn": "70.00",
                    "dimensions": {"department": "SHOP-A", "order": "A"},
                    "opening": False,
                },
                {
                    "entry_id": 2,
                    "line_id": 2,
                    "source": "wip-b",
                    "account": "20",
                    "posting_date": "2026-10-10",
                    "side": "debit",
                    "amount_byn": "30.00",
                    "dimensions": {"department": "SHOP-B", "order": "A"},
                    "opening": False,
                },
                {
                    "entry_id": 3,
                    "line_id": 3,
                    "source": "other-order",
                    "account": "20",
                    "posting_date": "2026-10-10",
                    "side": "debit",
                    "amount_byn": "50.00",
                    "dimensions": {"department": "SHOP-A", "order": "OTHER"},
                    "opening": False,
                },
            ]
        }
    }

    class Account:
        def __init__(self, dimensions):
            self.required_dimensions = dimensions

    async def accounts(*_args, **_kwargs):
        return {"43": Account({"warehouse", "sku", "lot"}), "20": Account({"department", "order"})}

    async def costs(*_args, **_kwargs):
        return source

    async def validate(*_args, **_kwargs):
        return None

    monkeypatch.setattr(production_output_cost, "cost_sources", costs)
    monkeypatch.setattr(production_output_cost, "validate_accounts", accounts)
    monkeypatch.setattr(production_output_transfer, "validate_accounts", accounts)
    monkeypatch.setattr(production_output_transfer.service, "validate_posting", validate)
    posting = (
        await production_output_transfer.prepare_output_transfer(
            BasisSession(),
            11,
            "2026-10",
            command(department="FINISHED-GOODS"),
            Production(),
            object(),
        )
    )["posting_document"]
    assert posting["lines"][0]["account"] == "43"
    assert posting["lines"][0]["amount"] == "100.00"
    assert posting["lines"][0]["quantity"] == "2.00"
    credits = {
        (line["dimensions"]["department"], line["dimensions"]["order"]): line["amount"]
        for line in posting["lines"][1:]
    }
    assert credits == {("SHOP-A", "A"): "70.00", ("SHOP-B", "A"): "30.00"}
    remaining = {
        ("SHOP-A", "A"): Decimal("70.00"),
        ("SHOP-B", "A"): Decimal("30.00"),
        ("SHOP-A", "OTHER"): Decimal("50.00"),
    }
    for key, amount in credits.items():
        remaining[key] -= Decimal(amount)
    assert remaining == {
        ("SHOP-A", "A"): Decimal("0.00"),
        ("SHOP-B", "A"): Decimal("0.00"),
        ("SHOP-A", "OTHER"): Decimal("50.00"),
    }


@pytest.mark.asyncio
async def test_output_transfer_requires_exact_output_document_set(monkeypatch):
    async def fake_preview(*_args, **_kwargs):
        return review()

    monkeypatch.setattr(production_output_transfer, "preview_output_cost_basis", fake_preview)
    with pytest.raises(ValueError, match="Output document set"):
        await production_output_transfer.prepare_output_transfer(
            Session(policy()), 11, "2026-10", command(output_document_ids=[102]), object(), object()
        )


@pytest.mark.asyncio
async def test_output_transfer_preview_endpoint_is_private_and_company_scoped(
    client, book, monkeypatch
):
    async def fake_prepare(*_args, **_kwargs):
        return {
            "organization_id": book[0],
            "month": "2026-10",
            "policy_id": book[1],
            "scope": "production_output_cost_basis",
            "posting_available": True,
            "final_cost_certified": False,
        }

    monkeypatch.setattr(production_output_transfer, "prepare_output_transfer", fake_prepare)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/production-output-transfer-preview",
        json=command(policy_id=book[1]).model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["posting_available"] is True


def completion_package():
    import hashlib
    import json

    from modules.accounting import service
    from modules.accounting.schemas import PostingInput

    posting = PostingInput(source="production:output-transfer:11:42", source_version=1,
        operation="production_output_transfer", document_date="2026-10-10", operation_date="2026-10-10",
        posting_date="2026-10-31", policy_id=7, rule_version="production-output-transfer-v1",
        explanation="Synthetic output", lines=[
            {"account": "43", "side": "debit", "amount": "100", "quantity": "2",
             "dimensions": {"warehouse": "Main", "sku": "WIDGET", "lot": "LOT-1"}},
            {"account": "20", "side": "credit", "amount": "100", "dimensions": {"department": "SHOP", "order": "A"}},
        ])
    data = production_output_transfer.ProductionOutputTransferConfirmInput(**command().model_dump(),
        basis_digest="a" * 64, digest=service.digest(posting))
    raw = {"order_id": 42, "operation_date": "2026-10-10", "quantity": "2.00",
           "sku_code": "WIDGET", "lot": "LOT-1", "warehouse": "Main"}
    snapshot = {"command": raw}
    checksum = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    document = SimpleNamespace(id=101, request_id="synthetic-document", command=raw, snapshot=snapshot, digest=checksum)
    confirmation = SimpleNamespace(digest=checksum, quantity=Decimal("2"))
    basis = review()
    basis["output"]["documents"] = [{"document_id": 101, "request_id": document.request_id,
        "operation_date": "2026-10-10", "sku_code": "WIDGET", "lot": "LOT-1", "quantity": "2.00",
        "state": "accepted", "accepted_quantity": "2.00", "rejected_quantity": "0.00"}]
    entry = SimpleNamespace(id=50, organization_id=11, posting_date=date(2026, 10, 31),
        source=posting.source, source_version=1, operation=posting.operation, actor="tester", digest=data.digest)
    receipt = SimpleNamespace(entry_id=50, organization_id=11, order_id=42, month="2026-10", actor="tester",
        command=data.model_dump(mode="json"), basis=basis, posting=posting.model_dump(mode="json"),
        basis_digest=data.basis_digest, digest=data.digest)
    return entry, receipt, posting, data, document, confirmation


class CompletionSession:
    def __init__(self, rows, controls, *, closed=False):
        self.rows, self.controls = rows, controls
        self.closed = closed
        self.flushes = 0

    async def execute(self, _statement):
        return SimpleNamespace(all=lambda: self.rows)

    async def scalars(self, _statement):
        return SimpleNamespace(all=lambda: self.controls)

    async def scalar(self, _statement):
        return SimpleNamespace(closed=self.closed)

    async def flush(self):
        self.flushes += 1


@pytest.mark.parametrize("existing,closed", [(None, False), (50, False), (50, True)])
async def test_source_completion_links_pending_only_and_replays_without_writes(monkeypatch, existing, closed):
    from modules.accounting import closing_commands

    entry, receipt, posting, _, document, confirmation = completion_package()

    async def actual(*_args):
        return posting

    monkeypatch.setattr(closing_commands, "actual_posting", actual)
    control = SimpleNamespace(source="production:output:101", version=1, month="2026-10", entry_id=existing)
    session = CompletionSession([(document, confirmation)], [control], closed=closed)
    await production_output_transfer.complete_output_sources(session, 11, "2026-10", receipt, entry)
    assert control.entry_id == 50
    assert session.flushes == (1 if existing is None else 0)


@pytest.mark.parametrize("case", ["conflict", "version", "month", "closed_pending", "missing", "extra_document", "cross_month", "posting"])
async def test_source_completion_rejects_conflicts_before_any_control_write(monkeypatch, case):
    from modules.accounting import closing_commands

    entry, receipt, posting, _, document, confirmation = completion_package()
    control = SimpleNamespace(source="production:output:101", version=1, month="2026-10", entry_id=None)
    rows, controls = [(document, confirmation)], [control]
    if case == "conflict":
        control.entry_id = 999
    elif case == "version":
        control.version = 2
    elif case == "month":
        control.month = "2026-09"
    elif case == "missing":
        controls = []
    elif case == "extra_document":
        rows += [(SimpleNamespace(id=102), confirmation)]
    elif case == "cross_month":
        document.command["operation_date"] = "2026-09-30"
    elif case == "posting":
        posting = posting.model_copy(update={"explanation": "Tampered"})

    async def actual(*_args):
        return posting

    monkeypatch.setattr(closing_commands, "actual_posting", actual)
    session = CompletionSession(rows, controls, closed=case == "closed_pending")
    original = control.entry_id
    with pytest.raises(production_output_transfer.AccountingError):
        await production_output_transfer.complete_output_sources(session, 11, "2026-10", receipt, entry)
    assert control.entry_id == original and session.flushes == 0


@pytest.mark.parametrize("path", ["existing", "posted_existing_receipt", "new"])
async def test_every_success_path_completes_exact_receipt_without_reposting_existing(monkeypatch, path):
    entry, receipt, posting, data, _, _ = completion_package()
    completed, posted = [], []

    class ConfirmSession(Session):
        async def get(self, _model, _key):
            return None if path == "new" else receipt

    async def lock(*_args):
        return None

    async def prepare(*_args):
        return {"basis_digest": data.basis_digest, "digest": data.digest, "posting_document": posting.model_dump(mode="json"), **receipt.basis}

    async def post(*_args, **_kwargs):
        posted.append(entry.id)
        return entry

    async def complete(_session, org, month, saved, actual):
        completed.append((org, month, saved.entry_id, actual.id))

    monkeypatch.setattr(production_output_transfer.service, "lock_organization", lock)
    monkeypatch.setattr(production_output_transfer, "prepare_output_transfer", prepare)
    monkeypatch.setattr(production_output_transfer.service, "post", post)
    monkeypatch.setattr(production_output_transfer, "complete_output_sources", complete)
    session = ConfirmSession(entry if path == "existing" else None)
    result = await production_output_transfer.confirm_output_transfer(session, 11, "2026-10", data, "tester",
        production=object(), warehouse_gateway=object())
    assert result is entry and completed == [(11, "2026-10", 50, 50)]
    assert posted == ([] if path == "existing" else [50])
