"""БД-зависимые тесты модуля Sales (SQLite в памяти)."""


async def test_create_and_list_deal(api):
    r = await api.post(
        "/sales/deals",
        json={
            "number": "CRM-T-1",
            "title": "Тест",
            "counterparty": "ООО Тест",
            "amount": 1000,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] is not None
    assert body["number"] == "CRM-T-1"
    assert body["stage"] == "new"

    r2 = await api.get("/sales/deals")
    assert r2.status_code == 200
    numbers = [d["number"] for d in r2.json()]
    assert "CRM-T-1" in numbers


async def test_unique_number(api):
    payload = {"number": "CRM-DUP", "title": "A", "counterparty": "X"}
    r1 = await api.post("/sales/deals", json=payload)
    assert r1.status_code == 201
    # повторный тот же номер → нарушение уникальности → 409
    r2 = await api.post("/sales/deals", json=payload)
    assert r2.status_code == 409


async def test_board_groups_by_stage(api):
    await api.post("/sales/deals", json={"number": "B1", "title": "t", "counterparty": "c", "stage": "new", "amount": 100})
    await api.post(
        "/sales/deals",
        json={"number": "B2", "title": "t", "counterparty": "c", "stage": "won", "amount": 200, "closed_date": "01.01.2025"},
    )

    r = await api.get("/sales/board")
    assert r.status_code == 200
    data = r.json()
    assert len(data["stages"]) == 5
    stages = {s["id"]: s for s in data["stages"]}
    assert stages["new"]["count"] == 1
    assert stages["new"]["sum"] == 100
    assert stages["won"]["count"] == 1
    assert stages["won"]["sum"] == 200
    assert stages["new"]["title"] == "Новая заявка"


async def test_get_deal_by_id(api):
    created = (
        await api.post(
            "/sales/deals",
            json={"number": "G1", "title": "Деталь", "counterparty": "ООО Икс", "owner": "Иванов И.И."},
        )
    ).json()
    r = await api.get(f"/sales/deals/{created['id']}")
    assert r.status_code == 200
    assert r.json()["counterparty"] == "ООО Икс"

    assert (await api.get("/sales/deals/999999")).status_code == 404


async def test_update_deal_stage(api):
    created = (
        await api.post("/sales/deals", json={"number": "U1", "title": "t", "counterparty": "c", "stage": "new"})
    ).json()

    r = await api.patch(f"/sales/deals/{created['id']}", json={"stage": "won"})
    assert r.status_code == 200
    assert r.json()["stage"] == "won"

    board = (await api.get("/sales/board")).json()
    stages = {s["id"]: s for s in board["stages"]}
    assert stages["won"]["count"] == 1
    assert stages["new"]["count"] == 0

    assert (await api.patch("/sales/deals/999999", json={"stage": "won"})).status_code == 404


async def test_kpis(session, api):
    from datetime import date

    from modules.sales.models import Activity, KpiTarget

    session.add(KpiTarget(key="calls_all", title="Всего звонков", target=100, unit="count", icon="phone", tone="indigo", sort_order=1))
    for _ in range(3):
        session.add(Activity(kpi_key="calls_all", value=1, date=date(2026, 6, 2)))
    await session.commit()

    r = await api.get("/sales/kpis")
    assert r.status_code == 200
    item = next(x for x in r.json() if x["key"] == "calls_all")
    assert item["actual"] == 3
    assert item["target"] == 100
    assert item["percent"] == 3


async def test_deal_items(session, api):
    from core.domain.models import Sku
    from modules.sales.models import DealItem

    deal = (
        await api.post("/sales/deals", json={"number": "IT-1", "title": "t", "counterparty": "c"})
    ).json()
    sku = Sku(code="SKU-1", title="Тестовая позиция", unit="шт")
    session.add(sku)
    await session.flush()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=2))
    await session.commit()

    r = await api.get(f"/sales/deals/{deal['id']}")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "Тестовая позиция"
    assert body["items"][0]["qty"] == 2
    assert body["items"][0]["code"] == "SKU-1"


async def test_log_activity_increments_kpi(session, api):
    from datetime import date

    from modules.sales.models import Activity, KpiTarget

    session.add(KpiTarget(key="calls_all", title="Всего звонков", target=100, unit="count", icon="phone", tone="indigo", sort_order=1))
    session.add(Activity(kpi_key="calls_all", value=1, date=date(2026, 6, 2)))
    await session.commit()

    before = next(x for x in (await api.get("/sales/kpis")).json() if x["key"] == "calls_all")
    assert before["actual"] == 1

    r = await api.post("/sales/activities", json={"kpi_key": "calls_all"})
    assert r.status_code == 201

    after = next(x for x in (await api.get("/sales/kpis")).json() if x["key"] == "calls_all")
    assert after["actual"] == 2
    assert after["percent"] == 2


async def test_outbox_emit_and_relay(session):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent
    from core.services.eventbus import OutboxEventBus

    bus = OutboxEventBus()
    seen: list[dict] = []
    bus.subscribe("test.evt", lambda p: seen.append(p))

    bus.emit(session, "test.evt", {"x": 1})
    await session.commit()

    rows = (await session.execute(select(OutboxEvent))).scalars().all()
    assert len(rows) == 1 and rows[0].processed_at is None

    assert await bus.relay_once(session) == 1
    assert seen == [{"x": 1}]
    rows = (await session.execute(select(OutboxEvent))).scalars().all()
    assert rows[0].processed_at is not None
    # повторный relay — нечего доставлять
    assert await bus.relay_once(session) == 0


async def test_deal_create_emits_outbox(session, api):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent

    await api.post("/sales/deals", json={"number": "OBX-1", "title": "t", "counterparty": "c"})
    rows = (
        await session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "sales.deal.created")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].payload["number"] == "OBX-1"


async def test_create_invoice_writes_to_1c(session, api):
    from sqlalchemy import select

    from core.domain.models import AuditLog, OutboxEvent
    from core.services.eventbus import OutboxEventBus

    deal = (
        await api.post(
            "/sales/deals",
            json={"number": "DOC-1", "title": "Поставка АКБ", "counterparty": "ООО Альфа", "amount": 5000},
        )
    ).json()

    # формируем счёт → он записывается в 1С (mock) и помечается posted
    r = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "invoice"})
    assert r.status_code == 201
    doc = r.json()
    assert doc["kind"] == "invoice"
    assert doc["number"] == "СЧ-DOC-1"
    assert doc["status"] == "posted"
    assert doc["onec_ref"] == "1С-СЧ-DOC-1"
    assert doc["amount"] == 5000

    # документ виден в карточке сделки
    detail = (await api.get(f"/sales/deals/{deal['id']}")).json()
    assert len(detail["documents"]) == 1
    assert detail["documents"][0]["onec_ref"] == "1С-СЧ-DOC-1"

    # запись в 1С → доменное событие в шину (часть 3) → проекция в audit (часть 5)
    rows = (await session.execute(select(OutboxEvent))).scalars().all()
    posted = [e for e in rows if e.event_type == "sales.document.posted"]
    assert len(posted) == 1
    assert posted[0].payload["onec_ref"] == "1С-СЧ-DOC-1"

    await OutboxEventBus().relay_once(session)
    audit = (await session.execute(select(AuditLog))).scalars().all()
    assert any(a.action == "sales.document.posted" and a.entity_ref == f"deal:{deal['id']}" for a in audit)

    # несуществующая сделка → 404
    assert (await api.post("/sales/deals/999999/documents", json={"kind": "invoice"})).status_code == 404


async def test_contract_goes_through_approval(session, api):
    from sqlalchemy import select

    from core.domain.models import Approval, OutboxEvent

    deal = (
        await api.post(
            "/sales/deals",
            json={"number": "CT-1", "title": "Поставка", "counterparty": "ООО Бета", "amount": 12000},
        )
    ).json()

    # договор НЕ пишется в 1С сразу — сначала уходит на согласование юристу (ч.4)
    r = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "contract"})
    assert r.status_code == 201
    doc = r.json()
    assert doc["kind"] == "contract"
    assert doc["number"] == "ДГ-CT-1"
    assert doc["status"] == "pending_approval"
    assert doc["onec_ref"] is None

    # на документ создано согласование с маршрутом «Юрист»
    appr = (
        await session.execute(
            select(Approval).where(Approval.entity_ref == f"document:{doc['id']}")
        )
    ).scalars().first()
    assert appr is not None
    assert appr.kind == "deal.contract"
    assert appr.route == "Юрист"
    assert appr.status == "pending"

    # одобрение → документ проводится в 1С
    d = await api.post(
        f"/sales/documents/{doc['id']}/decide", json={"approved": True, "by": "Юрист Юрьев"}
    )
    assert d.status_code == 200
    body = d.json()
    assert body["status"] == "posted"
    assert body["onec_ref"] == "1С-ДГ-CT-1"

    # связанное согласование закрыто
    await session.refresh(appr)
    assert appr.status == "approved"

    # события: создание документа + решение согласования + проведение в 1С
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "sales.document.created" in types
    assert "approval.approved" in types
    assert "sales.document.posted" in types

    # повторное решение запрещено — документ уже не на согласовании
    assert (
        await api.post(f"/sales/documents/{doc['id']}/decide", json={"approved": True})
    ).status_code == 409


async def test_contract_rejected(session, api):
    deal = (
        await api.post(
            "/sales/deals", json={"number": "CT-2", "title": "t", "counterparty": "ООО Гамма"}
        )
    ).json()
    doc = (
        await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "contract"})
    ).json()

    d = await api.post(f"/sales/documents/{doc['id']}/decide", json={"approved": False, "by": "Юрист"})
    assert d.status_code == 200
    assert d.json()["status"] == "rejected"
    assert d.json()["onec_ref"] is None


async def test_decide_document_rbac_enforced(session, api):
    deal = (
        await api.post("/sales/deals", json={"number": "CT-3", "title": "t", "counterparty": "c"})
    ).json()
    doc = (
        await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "contract"})
    ).json()

    # роль без права согласования (латиницей — заголовки только ASCII) → 403
    denied = await api.post(
        f"/sales/documents/{doc['id']}/decide",
        json={"approved": True},
        headers={"X-User-Roles": "guest"},
    )
    assert denied.status_code == 403


async def test_approval_request_and_decide(session, api):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent

    deal = (
        await api.post("/sales/deals", json={"number": "APR-1", "title": "t", "counterparty": "ООО Згода"})
    ).json()

    r = await api.post(
        f"/sales/deals/{deal['id']}/request-approval",
        json={"kind": "deal.contract", "requested_by": "Менеджер"},
    )
    assert r.status_code == 201
    appr = r.json()
    assert appr["status"] == "pending"
    assert appr["route"] == "Юрист"

    pending = (await api.get("/approvals?status=pending")).json()
    assert any(a["id"] == appr["id"] for a in pending)

    by_ref = (await api.get(f"/approvals?entity_ref=deal:{deal['id']}")).json()
    assert len(by_ref) == 1

    decided = await api.post(f"/approvals/{appr['id']}/approve", json={"by": "Юрист Юрьев"})
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"

    # повторное решение запрещено
    assert (await api.post(f"/approvals/{appr['id']}/approve", json={})).status_code == 409

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "approval.requested" in types
    assert "approval.approved" in types


async def test_approval_escalation(session):
    from datetime import datetime

    from core.domain.models import Approval
    from core.services.approvals import ApprovalService
    from core.services.eventbus import OutboxEventBus

    svc = ApprovalService(OutboxEventBus())
    overdue = Approval(
        kind="deal.contract", entity_ref="deal:1", subject="x", route="Юрист",
        due_at=datetime(2020, 1, 1),
    )
    session.add(overdue)
    await session.commit()

    assert await svc.escalate_once(session) == 1
    await session.refresh(overdue)
    assert overdue.escalation_level == 1


async def test_rbac_approve_enforced(session, api):
    deal = (
        await api.post("/sales/deals", json={"number": "RB-1", "title": "t", "counterparty": "c"})
    ).json()
    appr = (
        await api.post(f"/sales/deals/{deal['id']}/request-approval", json={"kind": "deal.contract"})
    ).json()

    # роль без права (латиницей — HTTP-заголовки только ASCII) → 403
    denied = await api.post(
        f"/approvals/{appr['id']}/approve", json={"by": "x"}, headers={"X-User-Roles": "guest"}
    )
    assert denied.status_code == 403

    # без заголовка пользователь по умолчанию — Админ → 200
    ok = await api.post(f"/approvals/{appr['id']}/approve", json={"by": "Админ"})
    assert ok.status_code == 200


def test_has_permission_by_role():
    from core.runtime.contract import Role
    from core.services.auth import CurrentUser, has_permission

    class _Core:
        roles = [
            Role("Менеджер", ("sales.deal.read",)),
            Role("РОП", ("sales.deal.read", "sales.deal.approve")),
        ]

    core = _Core()
    assert has_permission(core, CurrentUser("u", ["Менеджер"]), "sales.deal.approve") is False
    assert has_permission(core, CurrentUser("u", ["РОП"]), "sales.deal.approve") is True
    assert has_permission(core, CurrentUser("u", ["Админ"]), "whatever") is True


async def test_audit_log_projection(session):
    from sqlalchemy import select

    from core.domain.models import AuditLog
    from core.services.eventbus import OutboxEventBus

    bus = OutboxEventBus()
    bus.emit(session, "test.audit", {"entity_ref": "deal:1", "by": "Иван"})
    await session.commit()
    await bus.relay_once(session)

    rows = (await session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].action == "test.audit"
    assert rows[0].actor == "Иван"
    assert rows[0].entity_ref == "deal:1"
