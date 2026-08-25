"""Регистрация PriceCostGateway при заданном onec_base_url."""
from __future__ import annotations

from types import SimpleNamespace

from modules.integrations.module import IntegrationsModule
from modules.integrations.price_cost import StockPriceCostSource


class _FakeCore:
    def __init__(self, onec_base_url: str = "") -> None:
        self.config = SimpleNamespace(
            onec_base_url=onec_base_url,
            onec_user="",
            onec_password="",
            egr_base_url="",
            telephony_originate_url="",
        )
        self.services = SimpleNamespace(
            onec=None, stock=None, registry=None, telephony=None, price_cost=None,
        )
        self._routers: list = []
        self._perms: list = []
        self._ticks: list = []

    def include_router(self, router, prefix="") -> None:
        self._routers.append((router, prefix))

    def declare_permissions(self, perms) -> None:
        self._perms.extend(perms)

    def on_tick(self, fn) -> None:
        self._ticks.append(fn)


def test_integrations_registers_price_cost_when_onec_configured():
    core = _FakeCore(onec_base_url="http://127.0.0.1:9/ka/odata")
    IntegrationsModule().register(core)  # type: ignore[arg-type]
    assert isinstance(core.services.price_cost, StockPriceCostSource)


def test_integrations_leaves_price_cost_none_without_onec():
    core = _FakeCore(onec_base_url="")
    IntegrationsModule().register(core)  # type: ignore[arg-type]
    assert core.services.price_cost is None


def test_integrations_preserves_configured_alfa_credentials():
    core = _FakeCore()
    core.config.alfa_base_url = "https://bank.example/api/"
    core.config.alfa_token = "token"
    core.config.alfa_account = "BY00TEST"

    IntegrationsModule().register(core)  # type: ignore[arg-type]

    assert core.services.bank.base_url == "https://bank.example/api"
    assert core.services.bank.token == "token"
    assert core.services.bank.account == "BY00TEST"
