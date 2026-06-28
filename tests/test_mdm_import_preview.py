"""REF3-9 — read-only health-проба моста кэш 1С → MDM (dry-run, без записи).

Мост ~4109 контрагентов откачен (реальный прогон — зона Синк). Здесь безопасная доля: по кэшу
1С (фасад ``onec``, только чтение) считаем would_create/would_match_by_unp/without_unp, НЕ вызывая
upsert. Фасад не подключён → 503 graceful.
"""
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from core.domain.models import Counterparty
from core.runtime.app import create_app
from core.runtime.deps import get_session
from core.services import mdm


class _FakeOneC:
    """Мок-фасад 1С: отдаёт заданный кэш контрагентов, ничего не пишет."""

    def __init__(self, cache: list[dict]):
        self._cache = cache

    async def fetch_counterparties(self) -> list[dict]:
        return self._cache

    async def fetch_stock(self) -> list[dict]:
        return []

    async def post_document(self, doc_type: str, payload: dict) -> dict:
        return {}


_CACHE = [
    {"name": "ООО А", "unp": "111"},      # новый → would_create
    {"name": "ООО Б", "unp": "222"},      # есть эталон → would_match_by_unp
    {"name": "Без УНП", "unp": None},     # нельзя сматчить → without_unp
]


@pytest_asyncio.fixture
async def api_with_onec(session):
    """API-клиент с подключённым мок-фасадом 1С (кэш ``_CACHE``)."""
    app = create_app()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    app.state.core.services.onec = _FakeOneC(_CACHE)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-User-Roles": "director"}
    ) as client:
        yield client


async def test_import_preview_counts_without_writing(session):
    session.add(Counterparty(name="Эталон Б", unp="222"))
    await session.commit()
    before = (await session.execute(select(func.count()).select_from(Counterparty))).scalar_one()

    res = await mdm.import_preview(session, _FakeOneC(_CACHE))
    assert res == {"total": 3, "would_create": 1, "would_match_by_unp": 1, "without_unp": 1}

    after = (await session.execute(select(func.count()).select_from(Counterparty))).scalar_one()
    assert after == before  # НИ ОДНОЙ записи не создано (только чтение)


async def test_import_preview_endpoint(api_with_onec, session):
    session.add(Counterparty(name="Эталон Б", unp="222"))
    await session.commit()
    r = await api_with_onec.get("/system/mdm/import-preview")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["would_match_by_unp"] == 1 and body["would_create"] == 1 and body["without_unp"] == 1


async def test_import_preview_no_facade_503(api_no_gateways):
    r = await api_no_gateways.get("/system/mdm/import-preview")
    assert r.status_code == 503  # фасад не подключён → graceful, не 500


async def test_import_preview_requires_refs_view(api_with_onec):
    r = await api_with_onec.get("/system/mdm/import-preview", headers={"X-User-Roles": "warehouse"})
    assert r.status_code in (401, 403)
