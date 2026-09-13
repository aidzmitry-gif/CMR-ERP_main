"""Loss commands through actual HTTP transactions and the frozen PostgreSQL proposal."""
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import OutboxEvent
from core.services.auth import CurrentUser
from modules.sales import deal_loss
from modules.sales.access import DealAccess
from modules.sales.deal_loss import DealLossRequest, DealLossResolution
from modules.sales.models import Deal
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401
from tests.test_deal_loss import endpoint, loss_command, resolution
from tests.test_invoice_issuance import seed


@pytest.mark.parametrize("action", ["finalize", "withdraw"])
async def test_pg_empty_loss_request_resolution_and_historical_replay(issuance_pg, action):  # noqa: F811
    api, factory = issuance_pg
    api.headers["X-Expected-Principal"] = "issuer"
    async with factory() as session:
        ids, _ = await seed(api, session)
    body = await loss_command(api, ids["org"])
    response = await api.post("/sales/deals/1/lose", json=body)
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["state"] == "pending"
    command = resolution(row)
    result = await api.post(endpoint(ids["org"], row, action), json=command)
    assert result.status_code == 200, result.text
    replay = await api.post(endpoint(ids["org"], row, action), json=command)
    assert replay.status_code == 200 and replay.json() == result.json(), replay.text
    original_replay = await api.post("/sales/deals/1/lose", json=body)
    assert original_replay.status_code == 200, original_replay.text
    async with factory() as session:
        assert (await session.get(Deal, 1)).stage == ("lost" if action == "finalize" else "new")
        assert await session.scalar(select(func.count()).select_from(DealLossRequest)) == 1
        assert await session.scalar(select(func.count()).select_from(DealLossResolution)) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "sales.deal.loss_requested")) == 1
        with pytest.raises(DBAPIError):
            await session.execute(text("TRUNCATE sales.deal_loss_resolution"))
        await session.rollback()


async def test_pg_loss_finalize_inside_savepoint(issuance_pg):  # noqa: F811
    api, factory = issuance_pg
    api.headers["X-Expected-Principal"] = "issuer"
    async with factory() as session:
        ids, _ = await seed(api, session)
    body = await loss_command(api, ids["org"])
    response = await api.post("/sales/deals/1/lose", json=body)
    assert response.status_code == 200, response.text
    requested = response.json()
    core = api._transport.app.state.core
    async with factory() as session:
        deal, docs, actor, user = await deal_loss.context(session, core, CurrentUser("issuer", ["director"]),
                                                         DealAccess("all"), 1, ids["org"])
        request = await session.get(DealLossRequest, requested["request_id"])
        async with session.begin_nested():
            result = await deal_loss.resolve(session, core, user, request, deal, docs, actor,
                                             deal_loss.ResolveInput(**resolution(requested)), "finalized")
        await session.commit()
        assert result["action"] == "finalized"
        assert (await session.get(Deal, 1)).stage == "lost"
