"""Dev-фикстура цены/себес (PC2): гейт окружения+флага (dev-only, прод никогда) и
детерминированные демо-значения только по реальным SKU. Демо помечено ``source='demo'``.
"""
from types import SimpleNamespace

from core.domain.models import Sku
from core.runtime.app import _register_dev_fixtures
from core.services.price_cost_demo import DemoPriceCostSource, _pseudo_cost_byn


def _svc(environment: str, price_cost=None):
    return SimpleNamespace(
        config=SimpleNamespace(environment=environment), price_cost=price_cost
    )


# ───────────────────────── гейт окружения+флага ─────────────────────────
def test_dev_fixture_off_without_flag(monkeypatch):
    monkeypatch.delenv("AIOS_DEMO_PRICE_COST", raising=False)
    svc = _svc("dev")
    _register_dev_fixtures(svc)
    assert svc.price_cost is None  # без флага — честное пустое (деградация)


def test_dev_fixture_on_with_flag_in_dev(monkeypatch):
    monkeypatch.setenv("AIOS_DEMO_PRICE_COST", "1")
    svc = _svc("dev")
    _register_dev_fixtures(svc)
    assert isinstance(svc.price_cost, DemoPriceCostSource)


def test_dev_fixture_never_in_prod(monkeypatch):
    monkeypatch.setenv("AIOS_DEMO_PRICE_COST", "1")
    svc = _svc("prod")
    _register_dev_fixtures(svc)
    assert svc.price_cost is None  # прод не активирует демо-деньги даже с флагом (PLATFORM #1)


def test_dev_fixture_does_not_override_real_source(monkeypatch):
    monkeypatch.setenv("AIOS_DEMO_PRICE_COST", "1")
    sentinel = object()
    svc = _svc("dev", price_cost=sentinel)
    _register_dev_fixtures(svc)
    assert svc.price_cost is sentinel  # реальный источник (из integrations) не затираем демо


# ───────────────────────── демо-источник по реальным SKU ─────────────────────────
async def test_demo_source_returns_only_known_skus(session):
    session.add(Sku(code="ACC-100", title="АКБ 100Ач"))
    await session.flush()
    out = await DemoPriceCostSource().get_item_price_cost(session, ["ACC-100", "NOPE-1"])
    assert set(out) == {"ACC-100"}  # по несуществующему коду данных нет (деградация)
    item = out["ACC-100"]
    assert item.source == "demo"
    assert item.currency == "BYN"
    assert item.cost_byn is not None and item.cost_byn > 0
    assert item.price_byn == round(item.cost_byn * 1.35, 2)  # демо-наценка связная


async def test_demo_source_is_deterministic(session):
    session.add(Sku(code="ACC-200", title="АКБ 200Ач"))
    await session.flush()
    src = DemoPriceCostSource()
    a = (await src.get_item_price_cost(session, ["ACC-200"]))["ACC-200"]
    b = (await src.get_item_price_cost(session, ["ACC-200"]))["ACC-200"]
    assert a.cost_byn == b.cost_byn == _pseudo_cost_byn("ACC-200")  # один код → одно значение


async def test_demo_source_empty_input(session):
    assert await DemoPriceCostSource().get_item_price_cost(session, []) == {}


def test_create_app_auto_wires_demo_source_under_flag(monkeypatch):
    """Сквозной шов: реальный create_app с dev+флагом сам регистрирует демо-источник
    (не только хелпер в изоляции). Без флага create_app оставляет price_cost=None."""
    from config.settings import get_settings
    from core.runtime.app import create_app

    monkeypatch.setenv("AIOS_ENVIRONMENT", "dev")
    monkeypatch.setenv("AIOS_DEMO_PRICE_COST", "1")
    get_settings.cache_clear()
    try:
        app = create_app()
        assert isinstance(app.state.core.services.price_cost, DemoPriceCostSource)
    finally:
        get_settings.cache_clear()  # не протекать закэшенными настройками в другие тесты
