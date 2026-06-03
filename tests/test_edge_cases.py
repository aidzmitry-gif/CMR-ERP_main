"""API-тесты крайних веток: 404/409/пустые ответы — добор покрытия ошибок."""


# --- Sales: отсутствующие сущности ---


async def test_sales_item_and_contact_404(api):
    assert (await api.patch("/sales/deal-items/999999", json={"qty": 2})).status_code == 404
    assert (await api.delete("/sales/deal-items/999999")).status_code == 404
    assert (
        await api.post("/sales/deals/999999/items", json={"sku_id": 1, "qty": 1})
    ).status_code == 404
    assert (
        await api.post("/sales/deals/999999/contacts", json={"full_name": "X"})
    ).status_code == 404
    assert (await api.patch("/sales/contacts/999999/primary")).status_code == 404


async def test_sales_missing_deal_returns_empty_lists(api):
    assert (await api.get("/sales/deals/999999/items")).json() == []
    assert (await api.get("/sales/deals/999999/contacts")).json() == []
    assert (await api.get("/sales/deals/999999/messages")).json() == []


async def test_sales_documents_404(api):
    assert (
        await api.post("/sales/deals/999999/documents", json={"kind": "invoice"})
    ).status_code == 404
    # решение по несуществующему документу
    assert (
        await api.post("/sales/documents/999999/decide", json={"approved": True})
    ).status_code == 404


async def test_price_info_empty(api):
    info = (await api.get("/sales/prices/NOPE-1")).json()
    assert info["last_price"] is None and info["count"] == 0


# --- Lead: 404 и недопустимые переходы ---


async def test_lead_404_paths(api):
    assert (await api.post("/sales/leads/999999/qualify")).status_code == 404
    assert (await api.post("/sales/leads/999999/route")).status_code == 404
    assert (await api.post("/sales/leads/999999/convert")).status_code == 404


async def test_lead_route_after_convert_conflicts(api):
    lead = (await api.post("/sales/leads", json={"source": "site", "company": "ООО Цикл"})).json()
    await api.post(f"/sales/leads/{lead['id']}/qualify")
    await api.post(f"/sales/leads/{lead['id']}/route")
    await api.post(f"/sales/leads/{lead['id']}/convert")
    # после конвертации повторное распределение запрещено
    assert (await api.post(f"/sales/leads/{lead['id']}/route")).status_code == 409


# --- ERP-модули: PATCH несуществующих + не-терминальные статусы ---


async def test_module_patch_404(api):
    assert (
        await api.patch("/procurement/requests/999999", json={"status": "received"})
    ).status_code == 404
    assert (await api.patch("/production/orders/999999", json={"status": "done"})).status_code == 404
    assert (
        await api.patch("/logistics/shipments/999999", json={"status": "delivered"})
    ).status_code == 404
    assert (await api.patch("/finance/payments/999999", json={"status": "paid"})).status_code == 404
    assert (await api.post("/marketing/campaigns/999999/launch")).status_code == 404


async def test_module_non_terminal_status_no_event(api):
    # PATCH в промежуточный статус не эмитит «терминальное» событие (ветка else)
    req = (
        await api.post("/procurement/requests", json={"supplier": "S", "item": "X", "qty": 1})
    ).json()
    r = await api.patch(f"/procurement/requests/{req['id']}", json={"status": "ordered"})
    assert r.status_code == 200 and r.json()["status"] == "ordered"

    pay = (await api.post("/finance/payments", json={"ref": "СЧ-Z", "amount": 10})).json()
    r2 = await api.patch(f"/finance/payments/{pay['id']}", json={"status": "processing"})
    assert r2.status_code == 200 and r2.json()["status"] == "processing"
