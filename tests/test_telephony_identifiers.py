"""Provider identifiers stay intact; only exact extensions reach the call column."""
import os
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.db.base import Base
from core.domain.models import AuditLog, OutboxEvent
from core.services.eventbus import EventContext, OutboxEventBus
from modules.integrations.telephony import parse_event
from modules.sales.calls import EVENT_HANDLERS, on_incoming_call
from modules.sales.models import CallLog, Deal

IDENTIFIERS = [
    pytest.param(None, None, id="missing"),
    pytest.param("", None, id="length-0"),
    pytest.param("0", "0", id="length-1"),
    pytest.param("101", "101", id="legacy-valid"),
    pytest.param("00101", "00101", id="leading-zeroes"),
    pytest.param("12345678", "12345678", id="length-8"),
    pytest.param("123456789", None, id="length-9"),
    pytest.param("1" * 19, None, id="length-19"),
    pytest.param("2" * 31, None, id="length-31"),
    pytest.param("101;102;103;104;105", None, id="synthetic-compound"),
    pytest.param("101/ABC:102@host:5060", None, id="synthetic-address"),
    pytest.param(" 101 ", None, id="whitespace"),
    pytest.param("101\n", None, id="newline"),
    pytest.param("١٠١", None, id="arabic-digits"),
    pytest.param("１０１", None, id="fullwidth-digits"),
    pytest.param(101, None, id="integer"),
    pytest.param(101.0, None, id="float"),
    pytest.param(True, None, id="boolean"),
    pytest.param(["101"], None, id="array"),
    pytest.param({"extension": "101"}, None, id="object"),
]


def _ctx(session):
    bus = OutboxEventBus()
    return EventContext(session=session, services=SimpleNamespace(event_bus=bus)), bus


@pytest.mark.parametrize("raw,expected", IDENTIFIERS)
def test_parser_preserves_provider_values_and_projects_exact_extensions(raw, expected):
    params = {
        "type": "transfer", "uniqueid": "SYNTHETIC-PARSE", "direct": "in",
        "code": raw, "totransfer": raw, "token": "synthetic-test-only",
        "phone": "375291234567",
    }
    original = deepcopy(params)

    parsed = parse_event(params)

    assert parsed["event_type"] == "telephony.call.transfer"
    payload = parsed["payload"]
    assert payload["provider_code"] == raw
    assert payload["provider_totransfer"] == raw
    assert payload["agent_ext"] == expected
    assert payload["to_ext"] == expected
    assert payload["phone_e164"] == "+375291234567"
    assert "token" not in payload
    assert params == original


@pytest.mark.parametrize("raw,expected", IDENTIFIERS)
@pytest.mark.parametrize("event_type", ["telephony.call.incoming", "telephony.call.transfer"])
async def test_legacy_consumer_projects_without_changing_payload(session, raw, expected, event_type):
    payload = {
        "call_id": "SYNTHETIC-LEGACY", "direction": "in",
        "agent_ext": raw, "to_ext": raw,
    }
    original = deepcopy(payload)
    ctx, _ = _ctx(session)

    await EVENT_HANDLERS[event_type](payload, ctx)
    await session.commit()

    call = (await session.execute(select(CallLog))).scalar_one()
    assert call.agent_ext == expected
    assert call.owner_id is None  # Valid syntax does not identify an employee.
    if event_type == "telephony.call.transfer" and expected is not None:
        assert call.comment == f"Перевод на {expected}"
    else:
        assert call.comment is None
    logged = (await session.execute(select(OutboxEvent))).scalar_one()
    assert logged.payload["agent_ext"] == expected
    assert payload == original


async def test_legacy_repeat_and_later_valid_extension(session):
    ctx, _ = _ctx(session)
    legacy = {"call_id": "SYNTHETIC-REPEAT", "direction": "in", "agent_ext": "x" * 19}
    original = deepcopy(legacy)
    for _ in range(2):
        await on_incoming_call(legacy, ctx)
        await session.commit()

    call = (await session.execute(select(CallLog))).scalar_one()
    assert call.agent_ext is None
    for value in ["00101", "1" * 31, "102"]:
        await on_incoming_call({**legacy, "agent_ext": value}, ctx)
        await session.commit()

    await session.refresh(call)
    assert call.agent_ext == "00101"
    assert call.owner_id is None
    assert legacy == original
    assert await session.scalar(select(func.count()).select_from(CallLog)) == 1
    assert await session.scalar(
        select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type == "sales.call.logged")
    ) == 1


async def _relay_and_check_audit(session, payload, event_type):
    original = deepcopy(payload)
    ctx, bus = _ctx(session)
    bus.subscribe(event_type, EVENT_HANDLERS[event_type])
    bus.emit(session, event_type, payload)
    await session.commit()
    assert await bus.relay_once(session, ctx, event_types=(event_type,)) == 1

    source = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == event_type)
    )).scalar_one()
    audit = (await session.execute(
        select(AuditLog).where(AuditLog.action == event_type)
    )).scalar_one()
    assert source.processed_at is not None
    assert source.payload == audit.detail == original
    assert payload == original


async def test_raw_provider_values_survive_relay_and_audit(session):
    parsed = parse_event({
        "type": "transfer", "uniqueid": "SYNTHETIC-AUDIT",
        "code": "x" * 19, "totransfer": "y" * 31,
    })
    await _relay_and_check_audit(session, parsed["payload"], parsed["event_type"])
    call = (await session.execute(select(CallLog))).scalar_one()
    assert call.agent_ext is None
    assert call.comment is None
    assert call.owner_id is None


@pytest.mark.integration
async def test_postgres_identifier_constraint_and_legacy_handler():
    """Opt-in real PG oracle; never uses the application/production database URL."""
    raw_url = os.environ.get("CRM_TELEPHONY_TEST_DATABASE_URL", "")
    if not raw_url:
        pytest.skip("Set CRM_TELEPHONY_TEST_DATABASE_URL to a dedicated loopback test database")
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or not (url.database or "").startswith("crm_tel_test")
        or url.query  # Disallow driver options that could override the checked host.
    ):
        pytest.skip("Telephony PG oracle requires loopback and a crm_tel_test database")

    schema = "telephony_test_" + uuid4().hex
    engine = create_async_engine(url).execution_options(schema_translate_map={None: schema, "sales": schema})
    tables = [Deal.__table__, CallLog.__table__, OutboxEvent.__table__, AuditLog.__table__]
    created = False
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=tables))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            # Prove the original varchar(8) failure without changing the model/schema.
            for length in [19, 31]:
                with pytest.raises(DBAPIError) as rejected:
                    async with session.begin_nested():
                        session.add(CallLog(call_id=f"BASELINE-{length}", agent_ext="1" * length))
                        await session.flush()
                sqlstate = getattr(rejected.value.orig, "sqlstate", None) or getattr(
                    rejected.value.orig, "pgcode", None,
                )
                assert sqlstate == "22001"
            assert await session.scalar(select(func.count()).select_from(CallLog)) == 0
            await session.commit()

            ctx, _ = _ctx(session)
            # Exercise the real handler against the unchanged PG varchar column.
            for raw, expected in [("1" * 19, None), ("2" * 31, None), ("12345678", "12345678"),
                                  ("123456789", None), ("١٠١", None), (101, None)]:
                payload = {"call_id": f"HANDLER-{uuid4().hex}", "direction": "in", "agent_ext": raw}
                original = deepcopy(payload)
                await on_incoming_call(payload, ctx)
                await session.commit()
                call = (await session.execute(
                    select(CallLog).where(CallLog.call_id == payload["call_id"])
                )).scalar_one()
                assert call.agent_ext == expected
                assert call.owner_id is None
                assert payload == original

            legacy = {"call_id": "PG-LEGACY-AUDIT", "direction": "in", "agent_ext": "x" * 19}
            await _relay_and_check_audit(session, legacy, "telephony.call.incoming")
            parsed = parse_event({
                "type": "transfer", "uniqueid": "PG-NEW-AUDIT",
                "code": "x" * 19, "totransfer": "y" * 31,
            })
            await _relay_and_check_audit(session, parsed["payload"], parsed["event_type"])
    finally:
        try:
            if created:
                # Only the schema generated above, never public/sales or an input path.
                async with engine.begin() as connection:
                    await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await engine.dispose()
