"""Добор покрытия ядра: зависимости, шина, Telegram, согласования, системные роуты."""
from types import SimpleNamespace

from sqlalchemy import text

# --- deps.get_session: реальная зависимость (в API-тестах она подменяется) ---


async def test_get_session_inits_engine_when_needed():
    from core.runtime.deps import get_session
    from core.services.db import Database

    db = Database(SimpleNamespace(database_url="sqlite+aiosqlite:///:memory:"))
    assert db.session_factory is None  # фабрика ещё не создана → get_session её инициализирует
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(core=SimpleNamespace(services=SimpleNamespace(db=db))))
    )
    gen = get_session(request)
    session = await gen.__anext__()
    try:
        assert (await session.execute(text("SELECT 1"))).scalar() == 1
    finally:
        await gen.aclose()


# --- eventbus: интроспекция нестандартного «обработчика» ---


def test_wants_ctx_handles_unsignaturable():
    from core.services.eventbus import _wants_ctx

    # объект без сигнатуры → inspect.signature бросает TypeError → безопасный False
    assert _wants_ctx(object()) is False


async def test_on_deal_created_handler_logs():
    from modules.sales.events import on_deal_created

    # одно-параметрический обработчик (без ctx) — просто логирует, без БД
    await on_deal_created({"number": "EVT-1", "title": "Демо"})


# --- Telegram: ветки команд бота ---


async def test_telegram_no_pending_approvals(api):
    r = await api.post("/telegram/webhook", json={"message": {"text": "/approvals", "chat": {"id": 1}}})
    assert "Нет согласований" in r.json()["text"]


async def test_telegram_approve_arg_validation(api):
    bad = await api.post("/telegram/webhook", json={"message": {"text": "/approve abc", "chat": {"id": 1}}})
    assert "Укажите номер" in bad.json()["text"]
    missing = await api.post("/telegram/webhook", json={"message": {"text": "/approve 999999", "chat": {"id": 1}}})
    assert "не найдено" in missing.json()["text"]


async def test_telegram_module_command_and_already_decided(api):
    # команда, объявленная модулем sales (/deals) — исполняется хендлер модуля
    deals = await api.post("/telegram/webhook", json={"message": {"text": "/deals", "chat": {"id": 1}}})
    assert deals.json()["text"]

    deal = (
        await api.post("/sales/deals", json={"number": "TG-X", "title": "t", "counterparty": "c"})
    ).json()
    appr = (
        await api.post(f"/sales/deals/{deal['id']}/request-approval", json={"kind": "deal.contract"})
    ).json()
    await api.post(f"/approvals/{appr['id']}/approve", json={"by": "X"})
    again = await api.post(
        "/telegram/webhook", json={"message": {"text": f"/approve {appr['id']}", "chat": {"id": 1}}}
    )
    assert "уже обработано" in again.json()["text"]


# --- Согласования: 404 и эндпоинт reject ---


async def test_approval_approve_404(api):
    assert (await api.post("/approvals/999999/approve", json={"by": "X"})).status_code == 404


async def test_approval_reject_endpoint(api):
    deal = (
        await api.post("/sales/deals", json={"number": "RJ-1", "title": "t", "counterparty": "c"})
    ).json()
    appr = (
        await api.post(f"/sales/deals/{deal['id']}/request-approval", json={"kind": "deal.contract"})
    ).json()
    r = await api.post(f"/approvals/{appr['id']}/reject", json={"by": "Юрист"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"


# --- Системные роуты: журнал событий и аудита ---


async def test_system_events_and_audit(api):
    await api.post("/sales/deals", json={"number": "SE-1", "title": "t", "counterparty": "c"})
    assert isinstance((await api.get("/system/events")).json(), list)
    assert isinstance((await api.get("/system/audit")).json(), list)
    assert (await api.get("/health")).json() == {"status": "ok"}
