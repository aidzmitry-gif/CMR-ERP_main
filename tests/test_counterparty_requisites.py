"""G09 API/SQLite checkpoint. Not proof of PostgreSQL locks or migration safety."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.domain.models import Contact, Counterparty, CounterpartyUnpConflict, SurvivorshipRule
from core.services import mdm, reference_import
from core.services.eventbus import OutboxEventBus

MNS = {
    "unp": "100582333", "name": "Название из МНС", "address": "Минск, Советская, 9",
    "status": "Действующий", "source": "mns_grp",
    "source_url": "https://grp.nalog.gov.by/api/grp-public/data?unp=100582333&charset=UTF-8&type=json",
    "fetched_at": "2026-09-08T12:00:00+00:00",
}


def registry(api, data=None, side_effect=None):
    lookup = AsyncMock(return_value=data or MNS, side_effect=side_effect)
    api._transport.app.state.core.services.registry = SimpleNamespace(lookup_strict=lookup)
    return lookup


def selection(*fields, data=None):
    row = data or MNS
    mapping = {"name": "name", "unp": "unp", "legal_address": "address", "registry_status": "status"}
    return {"unp": row["unp"], "fields": list(fields), "preview": {f: row[mapping[f]] for f in fields}}


async def create(api, **kwargs):
    response = await api.post("/system/mdm/counterparty", json={"manual": {"name": "Ручная компания", "unp": "100582333"}, **kwargs})
    assert response.status_code == 201, response.text
    return response.json()


async def card(api, receipt):
    response = await api.get(f"/system/mdm/counterparty/{receipt['id']}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_manual_create_reload_contacts_audit_and_clear(api, session):
    receipt = await create(api, manual={
        "name": "Ручная компания", "unp": "100582333", "legal_address": "Ручной адрес",
        "registry_status": "На проверке", "bank_name": "Банк", "bank_account": "DE89 3704 0044 0532 0130 00",
        "bank_bic": "COBADEFFXXX",
    }, contacts=[
        {"full_name": "Иван", "phone": "+375 (29) 123-45-67 доб. 2", "email": "IVAN@example.com", "is_primary": True},
        {"full_name": "Анна", "email": "anna@example.com"},
    ])
    session.expire_all()
    saved = await card(api, receipt)
    assert saved["requisites"]["bank_account"] == "DE89370400440532013000"
    assert saved["requisites"]["registry_status"] == "На проверке" and saved["is_active"] is True
    assert len(saved["contacts"]) == 2
    assert saved["contacts"][0]["email"] == "ivan@example.com"
    assert all(value["source"] == "manual" for value in saved["provenance"].values())
    assert saved["audit"][0]["action"] == "counterparty.created"
    assert saved["audit"][0]["actor"]
    response = await api.patch(f"/system/mdm/counterparty/{receipt['id']}", json={
        "expected_revision": saved["revision"], "manual": {"bank_name": "", "legal_address": None},
        "contacts": [{"id": saved["contacts"][0]["id"], "phone": None, "email": ""}],
    })
    assert response.status_code == 200, response.text
    updated = await card(api, receipt)
    assert updated["revision"] == saved["revision"] + 1
    assert updated["requisites"]["bank_name"] is updated["requisites"]["legal_address"] is None
    assert updated["contacts"][0]["phone"] is updated["contacts"][0]["email"] is None
    assert len(updated["audit"]) == 2
    no_op = await api.patch(f"/system/mdm/counterparty/{receipt['id']}", json={"expected_revision": updated["revision"]})
    assert no_op.json()["revision"] == updated["revision"]


async def test_registry_selection_only_changes_selected_fields(api, session):
    receipt = await create(api, manual={"name": "Ручная компания", "unp": MNS["unp"], "legal_address": "Свой адрес", "bank_name": "Свой банк"})
    await session.rollback()  # no open read transaction when invoking registry

    async def lookup(unp):
        assert unp == MNS["unp"] and not session.in_transaction()
        return MNS

    registry(api, side_effect=lookup)
    response = await api.patch(f"/system/mdm/counterparty/{receipt['id']}", json={
        "expected_revision": receipt["revision"], "registry": selection("name", "registry_status"),
    })
    assert response.status_code == 200, response.text
    saved = await card(api, receipt)
    assert saved["name"] == MNS["name"] and saved["requisites"]["registry_status"] == MNS["status"]
    assert saved["requisites"]["legal_address"] == "Свой адрес" and saved["requisites"]["bank_name"] == "Свой банк"
    assert saved["provenance"]["unp"]["source"] == "manual"
    assert saved["provenance"]["name"] == {"source": "mns_grp", "at": MNS["fetched_at"], "source_url": MNS["source_url"]}


@pytest.mark.parametrize("manual", [{}, {"bank_name": "Банк без подтверждения УНП"}])
async def test_registry_name_without_identity_confirmation_writes_nothing(api, session, manual):
    registry(api)
    response = await api.post("/system/mdm/counterparty", json={"manual": manual, "registry": selection("name")})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "unp_confirmation_required"
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 0


@pytest.mark.parametrize("source", ["mns_grp", "demo"])
async def test_create_from_explicit_registry_selection_labels_actual_source(api, source):
    data = {**MNS, "source": source, "source_url": MNS["source_url"] if source == "mns_grp" else None}
    registry(api, data)
    receipt = await create(api, manual={}, registry=selection("name", "unp", "legal_address", data=data))
    saved = await card(api, receipt)
    assert saved["provenance"]["name"]["source"] == source
    assert saved["provenance"]["unp"]["source"] == source
    assert "bank_name" not in saved["requisites"]


@pytest.mark.parametrize(("changed", "code", "http_status"), [
    ({"name": "Новое имя"}, "registry_changed", 409),
    ({"name": "X" * 256}, "invalid_upstream", 502),
])
async def test_registry_changed_or_overlong_rolls_back(api, changed, code, http_status):
    receipt = await create(api)
    registry(api, {**MNS, **changed})
    response = await api.patch(f"/system/mdm/counterparty/{receipt['id']}", json={
        "expected_revision": receipt["revision"], "manual": {"bank_name": "Не сохранять"}, "registry": selection("name"),
    })
    assert response.status_code == http_status and response.json()["detail"]["code"] == code
    saved = await card(api, receipt)
    assert saved["name"] == "Ручная компания" and saved["revision"] == receipt["revision"]
    assert "bank_name" not in saved["requisites"] and len(saved["audit"]) == 1


@pytest.mark.parametrize("body", [
    {"source": "mns_grp"}, {"fetched_at": "fake"}, {"manual": {"source": "mns_grp"}},
    {"manual": {"is_active": False}}, {"manual": {"name": ""}}, {"manual": {"unp": "x100582333"}},
    {"manual": {"bank_account": "DE00370400440532013000"}}, {"manual": {"bank_bic": "not a BIC"}},
    {"manual": {"legal_address": "NUL\u0000"}}, {"contacts": [{"full_name": "Иван", "email": "bad@@mail"}]},
    {"contacts": [{"full_name": "Иван", "phone": "abc"}]},
])
async def test_invalid_or_spoofed_input_has_no_partial_write(api, session, body):
    response = await api.post("/system/mdm/counterparty", json={"manual": {"name": "Компания"}, **body})
    assert response.status_code == 422, response.text
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 0


async def test_permission_and_contact_ownership(api):
    denied = await api.post("/system/mdm/counterparty", json={"manual": {"name": "X"}}, headers={"X-User-Roles": "sales"})
    assert denied.status_code == 403
    first = await create(api, contacts=[{"full_name": "Контакт"}])
    first_card = await card(api, first)
    second = await create(api, manual={"name": "Другая", "unp": "100582334"})
    response = await api.patch(f"/system/mdm/counterparty/{second['id']}", json={
        "expected_revision": second["revision"], "manual": {"name": "Не сохранять"},
        "contacts": [{"id": first_card["contacts"][0]["id"], "full_name": "Чужой"}],
    })
    assert response.status_code == 422
    assert (await card(api, second))["name"] == "Другая"


async def test_duplicate_create_and_historical_ambiguity(api, session):
    first = await create(api)
    response = await api.post("/system/mdm/counterparty", json={"manual": {"name": "Дубль", "unp": MNS["unp"]}})
    assert response.status_code == 409 and response.json()["detail"]["ids"] == [first["id"]]
    await session.execute(insert(Counterparty), {"name": "Исторический дубль", "unp": MNS["unp"]})
    await session.commit()
    response = await api.post("/system/mdm/counterparty", json={"manual": {"name": "Третий", "unp": MNS["unp"]}})
    assert response.status_code == 409 and len(response.json()["detail"]["ids"]) == 2


async def test_external_orm_and_contacts_invalidate_revision_once(api, session):
    receipt = await create(api, contacts=[{"full_name": "Контакт"}])
    cp = await session.get(Counterparty, receipt["id"])
    contact = (await session.scalars(select(Contact).where(Contact.counterparty_id == cp.id))).one()
    version = cp.revision
    cp.name = "Из другого ORM пути"
    contact.phone = "+375 29 111-22-33"
    await session.commit()
    assert cp.revision == version + 1
    response = await api.patch(f"/system/mdm/counterparty/{cp.id}", json={"expected_revision": version, "manual": {"name": "Старый preview"}})
    assert response.status_code == 409
    await session.refresh(cp)
    version = cp.revision
    contact.phone = "+375 29 111-22-34"
    await session.commit()
    assert cp.revision == version + 1


async def test_two_sessions_optimistic_write_conflict(api, session):
    receipt = await create(api, contacts=[{"full_name": "Контакт"}])
    cp = await session.get(Counterparty, receipt["id"])
    contact_id = (await session.scalars(select(Contact.id).where(Contact.counterparty_id == cp.id))).one()
    old_revision = cp.revision
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as other:
        external = await other.get(Counterparty, cp.id)
        external.name = "Из другой сессии"
        await other.commit()
    assert cp.revision == old_revision
    response = await api.patch(f"/sales/contacts/{contact_id}/primary")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "stale_revision"
    assert "ids" not in response.json()["detail"]
    await session.rollback()  # fixture shares a session; production dependency closes it on failure
    saved = await card(api, receipt)
    assert saved["name"] == "Из другой сессии" and saved["contacts"][0]["is_primary"] is False


async def test_legacy_sales_contract_collision_is_safe_409(api, session):
    await create(api)
    template = await api.post("/sales/contract-templates", json={"code": "collision", "name": "Договор", "body": "{{buyer.name}}"})
    assert template.status_code == 201
    deal = await api.post("/sales/deals", json={"number": "COLLISION", "title": "Проверка", "counterparty": "Другая компания"})
    assert deal.status_code == 201
    response = await api.post(f"/sales/deals/{deal.json()['id']}/contract", json={"template_code": "collision", "unp": MNS["unp"]})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "duplicate_unp"
    assert "ids" not in response.json()["detail"]
    await session.rollback()
    assert await session.scalar(select(func.count()).select_from(Counterparty).where(Counterparty.name == "Другая компания")) == 0


async def test_merge_empty_unp_and_pending_transfer_preserve_provenance(session):
    source = {"source": "mns_grp", "at": MNS["fetched_at"], "source_url": MNS["source_url"]}
    survivor = Counterparty(name="", unp=None)
    duplicate = Counterparty(name=MNS["name"], unp=MNS["unp"], provenance={"name": source, "unp": source})
    session.add_all([survivor, duplicate])
    await session.commit()
    await mdm.merge(session, OutboxEventBus(), survivor.id, duplicate.id)
    await session.commit()
    assert survivor.unp == MNS["unp"] and survivor.provenance["name"] == source
    target = Counterparty(name="Перенос", unp=None)
    session.add(target)
    await session.flush()
    survivor.unp, target.unp = None, survivor.unp
    await session.commit()
    assert target.unp == MNS["unp"]


async def test_pending_new_duplicate_is_rejected(session):
    session.add_all([Counterparty(name="A", unp=MNS["unp"]), Counterparty(name="B", unp=MNS["unp"])])
    with pytest.raises(CounterpartyUnpConflict):
        await session.flush()
    await session.rollback()


@pytest.mark.parametrize("unrelated_change", [False, True])
async def test_stale_identity_map_cannot_hide_database_unp_collision(session, unrelated_change):
    cached = Counterparty(name="До внешнего изменения", unp=None)
    session.add(cached)
    await session.commit()
    existing_id = cached.id
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as other:
        external = await other.get(Counterparty, existing_id)
        external.unp = MNS["unp"]
        await other.commit()
    assert cached.unp is None  # the first session still holds the old identity snapshot
    if unrelated_change:
        cached.name = "Несвязанное изменение"
    session.add(Counterparty(name="Дубль", unp=MNS["unp"]))
    with pytest.raises(CounterpartyUnpConflict) as error:
        await session.flush()
    assert error.value.ids == [existing_id]
    await session.rollback()
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 1


async def test_mns_survives_1c_with_explicit_legacy_priority_and_metadata(api, session):
    registry(api)
    receipt = await create(api, manual={}, registry=selection("name", "unp"))
    session.add(SurvivorshipRule(entity_type="counterparty", field="name", strategy="source_priority", source_priority=["egr", "erp", "manual", "1c"]))
    await session.commit()
    await reference_import.upsert_counterparty(session, unp=MNS["unp"], name="Имя 1С", source="1c")
    await session.commit()
    saved = await card(api, receipt)
    assert saved["name"] == MNS["name"] and saved["provenance"]["name"]["source_url"] == MNS["source_url"]


@pytest.mark.parametrize(("strategy", "priority"), [("manual_only", []), ("source_priority", ["manual", "mns_grp", "1c"])])
async def test_operator_rule_protects_field_on_registry_apply(api, session, strategy, priority):
    receipt = await create(api)
    session.add(SurvivorshipRule(entity_type="counterparty", field="name", strategy=strategy, source_priority=priority))
    await session.commit()
    registry(api)
    response = await api.patch(f"/system/mdm/counterparty/{receipt['id']}", json={"expected_revision": receipt["revision"], "registry": selection("name")})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "protected_field"
    assert (await card(api, receipt))["name"] == "Ручная компания"
