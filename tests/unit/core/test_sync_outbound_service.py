from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.domain.models import SyncLink
from core.services import sync_outbound


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self


class Session:
    def __init__(self, results=(), entities=None):
        self.results = list(results)
        self.entities = entities or {}
        self.added = []

    async def execute(self, _statement):
        return self.results.pop(0)

    async def get(self, model, identity):
        return self.entities.get((model.__name__, identity))

    def add(self, value):
        self.added.append(value)


def test_payload_for_supports_known_master_data_and_rejects_unknown_types():
    assert sync_outbound._payload_for(
        "counterparty", SimpleNamespace(unp="123", name="ACME")
    ) == {"number": "123", "name": "ACME", "unp": "123"}
    assert sync_outbound._payload_for(
        "sku", SimpleNamespace(code="SKU-1", title="АКБ", unit="шт")
    ) == {"number": "SKU-1", "name": "АКБ", "unit": "шт"}
    with pytest.raises(ValueError, match="неизвестный entity_type"):
        sync_outbound._payload_for("deal", SimpleNamespace())


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_and_does_not_export_external_origin():
    session = Session([Result([])])
    link = await sync_outbound.enqueue(session, entity_type="sku", entity_id=7)
    assert link in session.added
    assert (link.origin, link.direction, link.state) == ("erp", "out", "pending")

    existing = SyncLink(
        id=2, entity_type="sku", entity_id=7, system="1c", origin="erp",
        direction="out", state="synced", error_text="old",
    )
    session = Session([Result([existing])])
    same = await sync_outbound.enqueue(session, entity_type="sku", entity_id=7)
    assert same is existing
    assert (existing.state, existing.error_text) == ("pending", None)

    external = SyncLink(
        id=3, entity_type="sku", entity_id=8, system="1c", origin="1c",
        direction="in", state="synced", error_text="kept",
    )
    session = Session([Result([external])])
    same = await sync_outbound.enqueue(session, entity_type="sku", entity_id=8)
    assert (same.state, same.error_text, same.origin) == ("synced", "kept", "1c")


@pytest.mark.asyncio
async def test_flush_pending_sends_success_and_records_per_link_errors():
    ok = SyncLink(
        id=1, entity_type="sku", entity_id=10, system="1c", origin="erp",
        direction="out", state="pending",
    )
    missing = SyncLink(
        id=2, entity_type="counterparty", entity_id=11, system="1c", origin="erp",
        direction="out", state="pending",
    )
    failing = SyncLink(
        id=3, entity_type="sku", entity_id=12, system="1c", origin="erp",
        direction="out", state="pending",
    )
    entity = SimpleNamespace(code="SKU-10", title="АКБ", unit="шт")
    gateway = SimpleNamespace(post_document=AsyncMock(side_effect=[{"ref": "1C-10"}, RuntimeError("1C down")]))
    session = Session(
        [Result([ok, missing, failing])],
        entities={("Sku", 10): entity, ("Sku", 12): entity},
    )
    result = await sync_outbound.flush_pending(session, gateway)
    assert result == {"sent": 1, "errors": 2, "skipped": 0}
    assert (ok.state, ok.external_ref, ok.error_text, ok.last_synced_at is not None) == (
        "synced", "1C-10", None, True
    )
    assert (missing.state, missing.error_text) == ("error", "запись не найдена")
    assert (failing.state, failing.error_text) == ("error", "1C down")
    assert gateway.post_document.await_count == 2
    assert await sync_outbound.flush_pending(session, None) == {
        "sent": 0,
        "errors": 0,
        "skipped": 0,
        "reason": "gateway недоступен",
    }


@pytest.mark.asyncio
async def test_journal_maps_sync_links_to_stable_audit_rows():
    link = SyncLink(
        id=4, entity_type="sku", entity_id=10, system="1c", origin="erp",
        direction="out", state="error", external_ref=None, error_text="bad",
    )
    rows = await sync_outbound.journal(Session([Result([link])]), limit=1)
    assert rows == [{
        "id": 4, "entity_type": "sku", "entity_id": 10, "system": "1c",
        "origin": "erp", "direction": "out", "state": "error",
        "external_ref": None, "last_synced_at": None, "error_text": "bad",
    }]
