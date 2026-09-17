from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.service import module


class Result:
    def __init__(self, row=None):
        self.row = row

    def scalars(self):
        return self

    def first(self):
        return self.row


class Session:
    def __init__(self, row=None):
        self.row = row
        self.added = []

    async def execute(self, _statement):
        return Result(self.row)

    def add(self, value):
        self.added.append(value)


@pytest.mark.asyncio
async def test_deal_won_handler_is_idempotent_and_creates_onboarding_request():
    await module.on_deal_won_create_request({"deal_id": 1}, None)
    await module.on_deal_won_create_request({}, SimpleNamespace(session=Session()))

    existing_session = Session(SimpleNamespace(id=9))
    await module.on_deal_won_create_request({"deal_id": 1}, SimpleNamespace(session=existing_session))
    assert existing_session.added == []

    session = Session()
    await module.on_deal_won_create_request(
        {"deal_id": 7, "number": "D-7", "counterparty": "ACME"},
        SimpleNamespace(session=session),
    )
    request = session.added[0]
    assert (request.deal_id, request.status, request.priority) == (7, "new", "normal")
    assert "D-7" in request.title and "ACME" in request.description


def test_service_module_registers_router_widget_and_event():
    class Core:
        def __init__(self):
            self.routers = []
            self.widgets = []
            self.subscriptions = []

        def include_router(self, router, *, prefix):
            self.routers.append((router, prefix))

        def register_widget(self, widget):
            self.widgets.append(widget)

        def subscribe(self, event_type, handler):
            self.subscriptions.append((event_type, handler))

    core = Core()
    service = module.ServiceModule()
    service.register(core)
    assert core.routers[0][1] == "/service"
    assert core.widgets[0].key == "service"
    assert core.subscriptions[0][0] == "sales.deal.won"
    assert module.get_module().name == "service"
