"""New UI capability contract; retain the accepted 395 proof cases unchanged."""
import pytest
from sqlalchemy import event, update

from core.domain.models import User
from core.runtime.contract import Role
from tests.test_office_warehouse_projection import prepared, source_state, url


@pytest.mark.parametrize("bound", [True, False])
async def test_warehouse_capability_requires_saved_binding_and_reads_without_dml(api, session, bound):
    _, _, doc = await prepared(api, session, bound=bound)
    endpoint = url(doc)
    before = await source_state(session)
    writes = []

    def observed(_conn, _cursor, sql, _parameters, _context, _many):
        if sql.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}:
            writes.append(sql)

    event.listen(session.bind.sync_engine, "before_cursor_execute", observed)
    try:
        response = await api.get(endpoint)
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", observed)
    assert response.status_code == 200, response.text
    assert response.json()["can_reconcile"] is bound
    assert response.json()["principal"] == "issuer"
    assert response.headers["cache-control"] == "private, no-store"
    assert writes == [] and await source_state(session) == before


async def test_reader_warehouse_capability_is_false_and_command_remains_forbidden(api, session, monkeypatch):
    _, _, doc = await prepared(api, session)
    core = api._transport.app.state.core
    monkeypatch.setattr(core, "roles", [role for role in core.roles if role.name != "assistant"]
                        + [Role("assistant", permissions=("office.doc.read",))])
    await session.execute(update(User).where(User.username == "issuer").values(role="assistant", deal_visibility="all"))
    await session.commit()
    headers = {"X-User-Roles": "assistant"}
    endpoint = url(doc)
    response = await api.get(endpoint, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["principal"] == "issuer" and response.json()["can_reconcile"] is False
    assert (await api.post(endpoint + "/reconcile", headers=headers)).status_code == 403


async def test_capability_uses_permissions_after_warehouse_wait(api, session, monkeypatch):
    _, _, doc = await prepared(api, session)
    core = api._transport.app.state.core
    role = Role("assistant", permissions=("office.doc.read", "office.stage.move"))
    monkeypatch.setattr(core, "roles", [row for row in core.roles if row.name != "assistant"] + [role])
    await session.execute(update(User).where(User.username == "issuer").values(role="assistant", deal_visibility="all"))
    await session.commit()
    service = core.services.wms_reservations
    original = service.invoice_shipping_progress

    async def revoked(*args, **kwargs):
        result = await original(*args, **kwargs)
        core.roles.remove(role)
        core.declare_role(Role(role.name, permissions=("office.doc.read",)))
        return result

    monkeypatch.setattr(service, "invoice_shipping_progress", revoked)
    response = await api.get(url(doc), headers={"X-User-Roles": role.name})
    assert response.status_code == 200, response.text
    assert response.json()["can_reconcile"] is False
