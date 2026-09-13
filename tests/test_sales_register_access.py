from sqlalchemy import select

from modules.accounting.models import AccessGrant


async def test_sales_reader_can_select_books_without_accounting_package(api, session):
    api.headers["X-User"] = "register-sales-reader"
    created = await api.post("/accounting/organizations", json={"name": "Sales reader book", "unp": "999999976"})
    assert created.status_code == 201, created.text
    grant = await session.scalar(select(AccessGrant).where(AccessGrant.organization_id == created.json()["id"]))
    grant.role = "reader"
    await session.commit()
    api.headers["X-User-Roles"] = "sales"
    assert (await api.get("/accounting/organizations")).status_code == 403
    response = await api.get("/sales/document-register/organizations")
    assert response.status_code == 200, response.text
    assert response.json() == [{"id": created.json()["id"], "name": "Sales reader book", "unp": "999999976"}]
    assert (await api.get("/sales/document-register/organizations", headers={"X-User": "no-grants"})).json() == []
