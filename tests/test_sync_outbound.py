"""Исходящая выгрузка ERP → 1С (M3): очередь sync_link, flush, идемпотентность, ошибки."""
import pytest
from sqlalchemy import select

from core.domain.models import Counterparty, SyncLink
from core.services import sync_outbound


async def _only_link(session) -> SyncLink:
    return (await session.execute(select(SyncLink))).scalars().first()


class _OkGateway:
    """Mock 1С: подтверждает документ ссылкой (как OneCClient.post_document)."""

    def __init__(self):
        self.calls = []

    async def post_document(self, doc_type, payload):
        self.calls.append((doc_type, payload))
        return {"ref": f"1С-{payload.get('number', '')}", "posted": True}


class _FailGateway:
    async def post_document(self, doc_type, payload):
        raise RuntimeError("1С недоступна")


async def _make_cp(session, **kw):
    cp = Counterparty(name=kw.get("name", "ООО ERP"), unp=kw.get("unp", "190777001"))
    session.add(cp)
    await session.flush()
    return cp


async def test_enqueue_creates_pending_link(session):
    cp = await _make_cp(session)
    link = await sync_outbound.enqueue(session, entity_type="counterparty", entity_id=cp.id)
    assert link.state == "pending"
    assert link.direction == "out"
    assert link.origin == "erp"
    assert link.external_ref is None


async def test_enqueue_idempotent(session):
    cp = await _make_cp(session)
    a = await sync_outbound.enqueue(session, entity_type="counterparty", entity_id=cp.id)
    await session.flush()
    b = await sync_outbound.enqueue(session, entity_type="counterparty", entity_id=cp.id)
    assert a.id == b.id  # тот же линк, не дубль


async def test_flush_pending_sends_and_marks_synced(session):
    cp = await _make_cp(session, unp="190777002")
    await sync_outbound.enqueue(session, entity_type="counterparty", entity_id=cp.id)
    await session.flush()

    gw = _OkGateway()
    summary = await sync_outbound.flush_pending(session, gw)
    assert summary == {"sent": 1, "errors": 0, "skipped": 0}
    assert len(gw.calls) == 1
    link = await _only_link(session)
    assert link.state == "synced"
    assert link.external_ref == "1С-190777002"
    assert link.last_synced_at is not None


async def test_flush_already_synced_not_resent(session):
    cp = await _make_cp(session, unp="190777003")
    await sync_outbound.enqueue(session, entity_type="counterparty", entity_id=cp.id)
    await session.flush()
    gw = _OkGateway()
    await sync_outbound.flush_pending(session, gw)
    # второй проход — pending пусто, повторной отправки нет
    summary = await sync_outbound.flush_pending(session, gw)
    assert summary["sent"] == 0
    assert len(gw.calls) == 1


async def test_flush_records_error_on_gateway_failure(session):
    cp = await _make_cp(session, unp="190777004")
    await sync_outbound.enqueue(session, entity_type="counterparty", entity_id=cp.id)
    await session.flush()

    summary = await sync_outbound.flush_pending(session, _FailGateway())
    assert summary == {"sent": 0, "errors": 1, "skipped": 0}
    link = await _only_link(session)
    assert link.state == "error"
    assert "1С недоступна" in link.error_text


async def test_flush_no_gateway_is_noop(session):
    cp = await _make_cp(session, unp="190777005")
    await sync_outbound.enqueue(session, entity_type="counterparty", entity_id=cp.id)
    await session.flush()
    summary = await sync_outbound.flush_pending(session, None)
    assert summary["sent"] == 0
    assert "gateway" in summary["reason"]


async def test_imported_record_not_enqueued_for_out(session):
    """Запись из 1С (origin!=erp) повторно не ставится в очередь на выгрузку."""
    cp = await _make_cp(session, unp="190777006")
    # линк, пришедший ИЗ 1С
    link = SyncLink(entity_type="counterparty", entity_id=cp.id, system="1c",
                    origin="1c", direction="in", state="synced", external_ref="1c-xxx")
    session.add(link)
    await session.flush()
    # повторный enqueue не должен переоткрыть его в pending (origin != erp)
    got = await sync_outbound.enqueue(session, entity_type="counterparty", entity_id=cp.id)
    assert got.id == link.id
    assert got.state == "synced"  # не сброшен в pending


async def test_flush_missing_entity_marks_error(session):
    # линк есть, а записи нет (удалена) → error, не падение
    link = SyncLink(entity_type="counterparty", entity_id=999999, origin="erp",
                    direction="out", state="pending")
    session.add(link)
    await session.flush()
    summary = await sync_outbound.flush_pending(session, _OkGateway())
    assert summary["errors"] == 1
    assert link.state == "error"
    assert link.error_text == "запись не найдена"


async def test_journal_returns_recent_links(session):
    cp = await _make_cp(session, unp="190777007")
    await sync_outbound.enqueue(session, entity_type="counterparty", entity_id=cp.id)
    await session.flush()
    entries = await sync_outbound.journal(session)
    assert len(entries) == 1
    assert entries[0]["entity_type"] == "counterparty"
    assert entries[0]["state"] == "pending"


async def test_payload_unknown_entity_raises():
    with pytest.raises(ValueError):
        sync_outbound._payload_for("unknown", object())
