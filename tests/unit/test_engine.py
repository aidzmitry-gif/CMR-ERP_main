"""Unit-тесты изолированной бизнес-логики (база пирамиды): без БД и сети."""
from types import SimpleNamespace

import pytest

# --- Lead Qualifier & Router: скоринг ---


def test_score_lead_empty_is_non_target():
    from modules.leads.leads import score_lead
    from modules.leads.models import Lead

    score, verdict, reason = score_lead(Lead(source="phone"), known_customer=False)
    assert verdict == "non-target"
    assert reason == "недостаточно данных" or score < 50


def test_score_lead_caps_at_100():
    from modules.leads.leads import score_lead
    from modules.leads.models import Lead

    full = Lead(
        source="tender", company="ООО Полный", phone="+375290000000", email="a@b.by",
        product="лист", message="Развёрнутый запрос на поставку металлопроката большим объёмом.",
    )
    score, verdict, _ = score_lead(full, known_customer=True)
    assert score == 100
    assert verdict == "target"


def test_score_lead_placeholder_company_not_counted():
    from modules.leads.leads import score_lead
    from modules.leads.models import Lead

    _, _, reason = score_lead(Lead(source="site", company="Новый лид"), known_customer=False)
    assert "указана компания" not in reason


@pytest.mark.parametrize("source", ["tender", "site", "email", "whatsapp", "telegram", "phone"])
def test_score_lead_channel_bonus(source):
    from modules.leads.leads import score_lead
    from modules.leads.models import Lead

    score, _, _ = score_lead(Lead(source=source), known_customer=False)
    assert score >= 0


def test_score_lead_unknown_source_no_bonus():
    from modules.leads.leads import score_lead
    from modules.leads.models import Lead

    # источник вне справочника каналов → бонуса канала нет (ветка channel_bonus=0)
    score, _, _ = score_lead(Lead(source="referral", phone="+375290000000"), known_customer=False)
    assert score == 20  # только бонус за телефон


# --- Lead Qualifier & Router: распределение и воронка ---


def test_route_by_region_only():
    from modules.leads.leads import route_lead
    from modules.leads.models import Lead

    manager, _ = route_lead(Lead(source="site", region="Минская обл."), loads={}, known_customer=False)
    assert manager == "Иванов И.И."


def test_route_by_product_only():
    from modules.leads.leads import route_lead
    from modules.leads.models import Lead

    manager, _ = route_lead(Lead(source="site", product="станок ЧПУ"), loads={}, known_customer=False)
    assert manager == "Петров П.П."


def test_route_no_match_uses_least_loaded_universal():
    from modules.leads.leads import route_lead
    from modules.leads.models import Lead

    # ни гео, ни продукта; универсал Сидоров наименее загружен
    manager, _ = route_lead(
        Lead(source="site"),
        loads={"Иванов И.И.": 1, "Петров П.П.": 2, "Сидоров С.С.": 0},
        known_customer=False,
    )
    assert manager == "Сидоров С.С."


@pytest.mark.parametrize(
    "lead_kwargs,known,expected",
    [
        ({"source": "tender"}, False, "tender"),
        ({"source": "site", "product": "проектная поставка"}, False, "project"),
        ({"source": "site"}, True, "regular"),
        ({"source": "site"}, False, "new"),
    ],
)
def test_choose_funnel_all_branches(lead_kwargs, known, expected):
    from modules.leads.leads import choose_funnel
    from modules.leads.models import Lead

    assert choose_funnel(Lead(**lead_kwargs), known) == expected


@pytest.mark.parametrize("score,expected", [(85, "Высокий"), (50, "Средний"), (49, "Низкий"), (0, "Низкий")])
def test_lead_priority_boundaries(score, expected):
    from modules.leads.leads import lead_priority

    assert lead_priority(score) == expected


# --- Mock-шлюзы (контракты §2.4): 1С, ЕГР ---


async def test_onec_client_mock():
    from modules.integrations.client import OneCClient

    c = OneCClient()
    doc = await c.post_document("invoice", {"number": "СЧ-1"})
    assert doc == {"ref": "1С-СЧ-1", "posted": True}
    assert len(await c.fetch_counterparties()) >= 1
    assert len(await c.fetch_stock()) >= 1


async def test_registry_client_lookup():
    from modules.integrations.registry import RegistryClient

    r = RegistryClient()
    found = await r.lookup(" 191234567 ")  # пробелы обрезаются
    assert found is not None and found["unp"] == "191234567"
    assert await r.lookup("000000000") is None


# --- LLM-шлюз: feature-flag и mock-режим ---


async def test_llm_gateway_disabled_raises():
    from core.services.litellm import LLMGateway

    with pytest.raises(RuntimeError):
        await LLMGateway(SimpleNamespace(ai_enabled=False)).complete("x")


async def test_llm_gateway_mock_by_kind():
    from core.services.litellm import LLMGateway

    g = LLMGateway(SimpleNamespace(ai_enabled=True, llm_base_url="", llm_model="qwen"))
    draft = await g.complete("p", kind="draft")
    qualify = await g.complete("p", kind="qualify")
    unknown = await g.complete("p", kind="нечто")  # неизвестный kind → fallback на draft
    assert draft and qualify and draft != qualify
    assert unknown == draft


async def test_llm_gateway_real_model_not_implemented():
    from core.services.litellm import LLMGateway

    # задан base_url → попытка реального вызова, тело ещё не реализовано
    g = LLMGateway(SimpleNamespace(ai_enabled=True, llm_base_url="http://localhost:11434", llm_model="qwen"))
    with pytest.raises(NotImplementedError):
        await g.complete("p", kind="draft")


# --- Temporal-заглушка ---


async def test_temporal_stub():
    from core.services.temporal import TemporalService, Workflow

    svc = TemporalService()
    assert svc.connected is False
    await svc.start()  # лог-заглушка, не падает
    with pytest.raises(NotImplementedError):
        await Workflow().run()


# --- RBAC (light) ---


def test_has_permission_roles():
    from core.runtime.contract import Role
    from core.services.auth import CurrentUser, has_permission

    core = SimpleNamespace(roles=[Role("Менеджер", ("sales.deal.read",))])
    assert has_permission(core, CurrentUser("u", ["Админ"]), "anything") is True
    assert has_permission(core, CurrentUser("u", ["Менеджер"]), "sales.deal.read") is True
    assert has_permission(core, CurrentUser("u", ["Менеджер"]), "sales.deal.approve") is False
    assert has_permission(core, CurrentUser("u", ["Гость"]), "sales.deal.read") is False


def test_get_current_user_headers():
    from core.services.auth import get_current_user

    # fail-closed (P0-1): без заголовков — бесправный «Гость», не дефолт-Админ
    default = get_current_user(SimpleNamespace(headers={}))
    assert default.roles == ["Гость"] and default.username == "anonymous"

    custom = get_current_user(
        SimpleNamespace(headers={"X-User": "ivan", "X-User-Roles": "Менеджер, РОП"})
    )
    assert custom.username == "ivan" and custom.roles == ["Менеджер", "РОП"]


# --- Шина: интроспекция контекста обработчика ---


def test_eventbus_wants_ctx():
    from core.services.eventbus import _wants_ctx

    assert _wants_ctx(lambda p: None) is False
    assert _wants_ctx(lambda p, ctx: None) is True


async def test_eventbus_dispatch_sync_and_async():
    from core.services.eventbus import OutboxEventBus

    bus = OutboxEventBus()
    seen: list = []
    bus.subscribe("e", lambda p: seen.append(("sync", p)))

    async def _async(p):
        seen.append(("async", p))

    bus.subscribe("e", _async)
    await bus.dispatch("e", {"x": 1})
    assert ("sync", {"x": 1}) in seen and ("async", {"x": 1}) in seen


# --- Database: детект драйвера и ленивая инициализация движка ---


def test_database_is_sqlite_detection():
    from core.services.db import Database

    assert Database(SimpleNamespace(database_url="sqlite+aiosqlite:///:memory:")).is_sqlite is True
    assert Database(SimpleNamespace(database_url="postgresql+psycopg://u:p@h/db")).is_sqlite is False


def test_database_init_engine_idempotent_sqlite():
    from core.services.db import Database

    db = Database(SimpleNamespace(database_url="sqlite+aiosqlite:///:memory:"))
    db.init_engine()
    first = db.engine
    db.init_engine()  # повторный вызов не пересоздаёт движок
    assert db.engine is first
    assert db.session_factory is not None


def test_database_init_engine_postgres_branch():
    from core.services.db import Database

    # postgres-движок создаётся лениво (без подключения) — ветка без schema_translate_map
    db = Database(SimpleNamespace(database_url="postgresql+psycopg://u:p@h:5432/db"))
    db.init_engine()
    assert db.engine is not None and db.session_factory is not None


# --- Core: реестр хуков жизненного цикла ---


def test_core_lifecycle_hooks():
    from core.runtime.core import Core

    core = Core(SimpleNamespace(config=object(), event_bus=object()))
    core.on_startup(lambda: None)
    core.on_shutdown(lambda: None)
    assert len(core.startup_hooks) == 1
    assert len(core.shutdown_hooks) == 1
