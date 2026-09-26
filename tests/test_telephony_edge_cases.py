"""Provider input and call-delivery regressions identified in the CI coverage report."""
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from core.domain.models import Contact, Counterparty, OutboxEvent, User
from core.services.eventbus import EventContext, OutboxEventBus
from modules.integrations.telephony import ZruchnaClient, normalize_e164, parse_event
from modules.sales import calls
from modules.sales.models import CallLog, CrmClient, CrmClientContact, Deal


@pytest.mark.parametrize("raw, expected", [
    ("01:02:03", 3723), ("02:03", 123), ("00:00", 0),
    ("1:2:3:4", None), ("bad:03", None), ("1:-2", None),
    ("-1", None), ("inf", None), ("NaN", None),
])
def test_provider_duration_formats_preserve_valid_values_and_reject_garbage(raw, expected):
    parsed = parse_event({"type": "hangup", "uniqueid": "DURATION", "duration": raw, "hold": raw})
    assert parsed["event_type"] == "telephony.call.ended"
    assert parsed["payload"]["duration_sec"] == expected
    assert parsed["payload"]["hold_sec"] == expected


@pytest.mark.parametrize("raw, expected", [("84951234567", "+74951234567"), ("441234567890", "+441234567890")])
def test_non_belarus_phone_keeps_country_code(raw, expected):
    assert normalize_e164(raw) == expected


@pytest.mark.parametrize("url", [None, 123, {"url": "https://pbx.test/call"}])
async def test_wrong_configuration_type_never_constructs_http_client(url, monkeypatch):
    def unexpected_client(**kwargs):
        pytest.fail("Invalid configuration must not reach the provider")

    monkeypatch.setattr("modules.integrations.telephony.httpx.AsyncClient", unexpected_client)
    gateway = ZruchnaClient(url)
    assert gateway.configured is False
    with pytest.raises(RuntimeError):
        await gateway.originate("101", "+375291234567")


@pytest.mark.parametrize("body", ["{broken", "[]"])
async def test_bad_json_body_preserves_authenticated_query_event(api, session, body, monkeypatch):
    monkeypatch.setattr(api._transport.app.state.core.config, "telephony_webhook_token", "synthetic-token")
    response = await api.post(
        "/integrations/telephony/zruchna",
        params={"token": "synthetic-token", "type": "in", "uniqueid": "QUERY-EVENT"},
        content=body, headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    event = (await session.execute(select(OutboxEvent))).scalar_one()
    assert event.event_type == "telephony.call.incoming"
    assert event.payload["call_id"] == "QUERY-EVENT"
    assert "token" not in event.payload


async def test_form_body_overrides_query_and_preserves_encoded_values(api, session, monkeypatch):
    monkeypatch.setattr(api._transport.app.state.core.config, "telephony_webhook_token", "synthetic-token")
    response = await api.post(
        "/integrations/telephony/zruchna?token=wrong&type=hangup&uniqueid=QUERY",
        data={"token": "synthetic-token", "type": "in", "uniqueid": "FORM",
              "phone": "+375291234567", "code": "001", "did": ""},
    )
    assert response.status_code == 200
    event = (await session.execute(select(OutboxEvent))).scalar_one()
    assert event.event_type == "telephony.call.incoming"
    assert event.payload["call_id"] == "FORM"
    assert event.payload["phone_e164"] == "+375291234567"
    assert event.payload["agent_ext"] == "001"
    assert event.payload["did"] is None
    assert "token" not in event.payload


def test_slow_sse_subscriber_does_not_drop_other_subscribers_or_old_cards(caplog):
    owner = "COVERAGE-SSE"
    slow, healthy = calls.subscribe(owner), calls.subscribe(owner)
    sentinel = {"call_id": "OLD"}
    try:
        assert calls.has_subscriber(owner)
        for _ in range(slow.maxsize):
            slow.put_nowait(sentinel)
        call = CallLog(call_id="NEW", direction="in", owner=owner, status="ringing")
        assert calls._push_card(call) is True
        card = healthy.get_nowait()
        call.status = "ended"
        assert card["call_id"] == "NEW"
        assert card["status"] == "ringing"  # queued snapshot does not follow later ORM mutations
        assert slow.qsize() == slow.maxsize
        assert slow.get_nowait() is sentinel
        assert "переполнена" in caplog.text
        calls.unsubscribe(owner, healthy)
        assert calls.has_subscriber(owner)
        slow.put_nowait(sentinel)
        assert calls._push_card(call) is False
    finally:
        calls.unsubscribe(owner, slow)
        calls.unsubscribe(owner, healthy)
    assert not calls.has_subscriber(owner)
    calls.unsubscribe(owner, healthy)  # disconnect retry is harmless


async def test_invalid_direct_handler_input_has_no_call_or_outbox_side_effects(session):
    ctx = EventContext(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))
    for handler in calls.EVENT_HANDLERS.values():
        await handler({"call_id": "VALID"}, None)  # legacy direct-call contract
        await handler({"call_id": "   "}, ctx)
    await session.flush()
    assert await session.scalar(select(func.count()).select_from(CallLog)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


async def test_answer_first_creates_one_log_and_late_metadata_fills_once(session):
    ctx = EventContext(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))
    await calls.on_call_answered({"call_id": "ANSWER-FIRST", "direction": "out"}, ctx)
    call = (await session.execute(select(CallLog))).scalar_one()
    answered_at = call.answered_at
    assert call.status == "answered"
    assert answered_at is not None
    await calls.on_call_answered({"call_id": "ANSWER-FIRST", "did": "LINE-A", "agent_ext": "001"}, ctx)
    await calls.on_call_answered({"call_id": "ANSWER-FIRST", "did": "LINE-B", "agent_ext": "002"}, ctx)
    await session.flush()
    assert call.did == "LINE-A"
    assert call.agent_ext == "001"
    assert call.answered_at == answered_at
    logged = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == "sales.call.logged"))).scalars().all()
    assert len(logged) == 1
    assert logged[0].payload["call_id"] == "ANSWER-FIRST"
    assert await session.scalar(select(func.count()).select_from(CallLog)) == 1


@pytest.mark.parametrize("status", ["busy", "failed"])
async def test_terminal_failure_keeps_zero_durations_in_call_and_event(session, status):
    ctx = EventContext(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))
    await calls.on_call_ended({"call_id": "FAILED-CALL", "event": "hangup", "status": status,
                               "duration_sec": 0, "hold_sec": 0}, ctx)
    call = (await session.execute(select(CallLog))).scalar_one()
    assert call.status == status
    assert call.duration_sec == 0
    assert call.hold_sec == 0
    assert call.ended_at is not None
    event = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == "sales.call.ended"))).scalar_one()
    assert event.payload["status"] == status
    assert event.payload["duration_sec"] == 0


@pytest.mark.parametrize("with_counterparty", [False, True])
async def test_contact_without_owned_deal_does_not_guess_employee(session, with_counterparty):
    cp = Counterparty(name="COVERAGE-UNASSIGNED", unp="190008812") if with_counterparty else None
    if cp is not None:
        session.add(cp)
        await session.flush()
    contact = Contact(full_name="Synthetic", phone="+375291234567", counterparty_id=cp.id if cp else None)
    session.add(contact)
    await session.flush()
    resolved = await calls.resolve_owner(session, "+375291234567")
    assert resolved == {"owner": "", "owner_id": None, "counterparty_id": cp.id if cp else None,
                        "contact_id": contact.id, "deal_id": None}


def _sales_user(employee_id, name, *, status="active", department="Продажи", role="sales"):
    return User(username=f"phone-owner-{employee_id}", full_name=name, employee_id=employee_id,
                department=department, role=role, status=status)


def _crm_client(name, owner_id, *, counterparty_id=None):
    key = name.lower().replace(" ", "-")
    return CrmClient(name=name, name_key=key, owner_id=owner_id, counterparty_id=counterparty_id,
                     request_key=f"phone-client-{key}", request_hash="a" * 64,
                     created_by="synthetic-telephony-test")


def _crm_contact(client_id, phone, key, *, is_primary=True):
    return CrmClientContact(crm_client_id=client_id, full_name="Synthetic CRM contact", phone=phone,
                            is_primary=is_primary, contact_key=key, request_key=key,
                            request_hash="b" * 64)


@pytest.mark.asyncio
async def test_resolve_owner_uses_full_normalized_crm_phone_not_same_nine_digit_legacy_contact(session):
    target_cp = Counterparty(name="CRM exact synthetic counterparty", unp="190009801")
    suffix_cp = Counterparty(name="False suffix synthetic counterparty", unp="190009802")
    session.add_all([
        target_cp, suffix_cp,
        _sales_user(781, "Confirmed client owner"),
        _sales_user(782, "Confirmed deal owner"),
    ])
    await session.flush()
    client = _crm_client("Exact phone target", 781, counterparty_id=target_cp.id)
    session.add(client)
    await session.flush()
    crm_contact = _crm_contact(client.id, "+375291112233", "exact-phone-contact")
    session.add(crm_contact)
    legacy_contact = Contact(full_name="Wrong suffix contact", phone="+7702291112233",
                             counterparty_id=suffix_cp.id, is_primary=True)
    session.add(legacy_contact)
    target_deal = Deal(number="PHONE-EXACT-CRM", title="Synthetic", counterparty="unrelated text",
                       crm_client_id=client.id, owner="Untrusted legacy owner text", owner_id=782,
                       stage="new")
    suffix_deal = Deal(number="PHONE-SUFFIX-LEGACY", title="Synthetic", counterparty=suffix_cp.name,
                       owner="Wrong suffix owner", stage="new")
    session.add_all([target_deal, suffix_deal])
    await session.flush()

    resolved = await calls.resolve_owner(session, "+375 29 111-22-33")

    assert resolved == {
        "owner": "Confirmed deal owner",
        "owner_id": 782,
        "counterparty_id": target_cp.id,
        "contact_id": None,
        "deal_id": target_deal.id,
    }


@pytest.mark.asyncio
async def test_resolve_owner_prefers_deal_bound_to_exact_crm_contact(session):
    session.add_all([
        _sales_user(901, "Confirmed client owner"),
        _sales_user(902, "Contact A deal owner"),
        _sales_user(903, "Contact B deal owner"),
    ])
    await session.flush()
    client = _crm_client("Contact-specific deals", 901)
    session.add(client)
    await session.flush()
    contact_a = _crm_contact(client.id, "+375291234571", "contact-a")
    contact_b = _crm_contact(client.id, "+375291234572", "contact-b", is_primary=False)
    session.add_all([contact_a, contact_b])
    await session.flush()
    deal_a = Deal(number="PHONE-CONTACT-A", title="Synthetic", counterparty="not used",
                  crm_client_id=client.id, crm_contact_id=contact_a.id,
                  owner="Untrusted owner A", owner_id=902, stage="new")
    deal_b = Deal(number="PHONE-CONTACT-B", title="Synthetic", counterparty="not used",
                  crm_client_id=client.id, crm_contact_id=contact_b.id,
                  owner="Untrusted owner B", owner_id=903, stage="prop")
    session.add_all([deal_a, deal_b])
    await session.flush()

    resolved = await calls.resolve_owner(session, "+375291234571")

    assert resolved == {
        "owner": "Contact A deal owner",
        "owner_id": 902,
        "counterparty_id": None,
        "contact_id": None,
        "deal_id": deal_a.id,
    }


@pytest.mark.asyncio
async def test_resolve_owner_does_not_choose_deal_bound_to_another_crm_contact(session):
    session.add_all([
        _sales_user(911, "Confirmed client owner"),
        _sales_user(912, "Other contact deal owner"),
    ])
    await session.flush()
    client = _crm_client("Other contact only deal", 911)
    session.add(client)
    await session.flush()
    contact_a = _crm_contact(client.id, "+375291234573", "caller-contact-a")
    contact_b = _crm_contact(client.id, "+375291234574", "other-contact-b", is_primary=False)
    session.add_all([contact_a, contact_b])
    await session.flush()
    deal_b = Deal(number="PHONE-OTHER-CONTACT-ONLY", title="Synthetic", counterparty="not used",
                  crm_client_id=client.id, crm_contact_id=contact_b.id,
                  owner="Untrusted other contact owner", owner_id=912, stage="new")
    session.add(deal_b)
    await session.flush()

    resolved = await calls.resolve_owner(session, "+375291234573")

    assert resolved == {
        "owner": "Confirmed client owner",
        "owner_id": 911,
        "counterparty_id": None,
        "contact_id": None,
        "deal_id": None,
    }


@pytest.mark.asyncio
async def test_legacy_exact_phone_resolves_client_and_deal_by_stable_ids_not_text(session):
    cp = Counterparty(name="Legacy stable-id synthetic", unp="190009803")
    session.add_all([cp, _sales_user(791, "Confirmed fallback owner"),
                     _sales_user(792, "Confirmed linked deal owner")])
    await session.flush()
    client = _crm_client("Legacy stable-id client", 791, counterparty_id=cp.id)
    session.add(client)
    await session.flush()
    legacy_contact = Contact(full_name="Exact legacy contact", phone="+375291234567",
                             counterparty_id=cp.id, is_primary=True)
    deal = Deal(number="PHONE-LEGACY-ID", title="Synthetic", counterparty="different display text",
                crm_client_id=client.id, owner="Untrusted legacy owner text", owner_id=792,
                stage="new")
    session.add_all([legacy_contact, deal])
    await session.flush()

    resolved = await calls.resolve_owner(session, "+375291234567")

    assert resolved == {
        "owner": "Confirmed linked deal owner",
        "owner_id": 792,
        "counterparty_id": cp.id,
        "contact_id": legacy_contact.id,
        "deal_id": deal.id,
    }


@pytest.mark.parametrize(
    ("deal_owner_ids", "expected_owner_id"),
    [((802, 802), 802), ((802, 803), 801)],
)
@pytest.mark.asyncio
async def test_multiple_active_crm_deals_choose_only_a_unique_owner_and_no_deal_id(
    session, deal_owner_ids, expected_owner_id
):
    session.add_all([
        _sales_user(801, "Confirmed client owner"),
        _sales_user(802, "Confirmed deal owner A"),
        _sales_user(803, "Confirmed deal owner B"),
    ])
    await session.flush()
    client = _crm_client(f"Multiple deals {expected_owner_id}", 801)
    session.add(client)
    await session.flush()
    session.add(_crm_contact(client.id, "+375291234568", f"multiple-deals-{expected_owner_id}"))
    session.add_all([
        Deal(number=f"PHONE-MULTI-{expected_owner_id}-1", title="Synthetic", counterparty="not used",
             crm_client_id=client.id, owner="Legacy owner A", owner_id=deal_owner_ids[0], stage="new"),
        Deal(number=f"PHONE-MULTI-{expected_owner_id}-2", title="Synthetic", counterparty="not used",
             crm_client_id=client.id, owner="Legacy owner B", owner_id=deal_owner_ids[1], stage="prop"),
    ])
    await session.flush()

    resolved = await calls.resolve_owner(session, "+375291234568")

    assert resolved["owner_id"] == expected_owner_id
    assert resolved["owner"] == {
        801: "Confirmed client owner",
        802: "Confirmed deal owner A",
    }[expected_owner_id]
    assert resolved["deal_id"] is None


@pytest.mark.asyncio
async def test_unconfirmed_active_deal_owner_falls_back_to_confirmed_client_owner(session):
    session.add_all([
        _sales_user(811, "Confirmed client owner"),
        _sales_user(812, "Inactive deal owner", status="inactive"),
    ])
    await session.flush()
    client = _crm_client("Inactive deal owner fallback", 811)
    session.add(client)
    await session.flush()
    session.add(_crm_contact(client.id, "+375291234569", "inactive-deal-owner"))
    deal = Deal(number="PHONE-INACTIVE-OWNER", title="Synthetic", counterparty="not used",
                crm_client_id=client.id, owner="Legacy owner text", owner_id=812, stage="new")
    session.add(deal)
    await session.flush()

    resolved = await calls.resolve_owner(session, "+375291234569")

    assert resolved["owner"] == "Confirmed client owner"
    assert resolved["owner_id"] == 811
    assert resolved["deal_id"] is None


@pytest.mark.asyncio
async def test_ambiguous_exact_crm_phone_across_clients_stays_unresolved(session):
    session.add_all([_sales_user(821, "Client owner A"), _sales_user(822, "Client owner B")])
    await session.flush()
    client_a = _crm_client("Ambiguous client A", 821)
    client_b = _crm_client("Ambiguous client B", 822)
    session.add_all([client_a, client_b])
    await session.flush()
    session.add_all([
        _crm_contact(client_a.id, "+375291234570", "ambiguous-phone-a"),
        _crm_contact(client_b.id, "+375291234570", "ambiguous-phone-b"),
    ])
    await session.flush()

    assert await calls.resolve_owner(session, "+375291234570") == {
        "owner": "", "owner_id": None, "counterparty_id": None,
        "contact_id": None, "deal_id": None,
    }
