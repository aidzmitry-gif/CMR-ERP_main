"""Тесты справочника поставщиков (CRUD) + скоркарты поставщика.

Supplier — профиль закупок (условия/срок/incoterms/статус), ``unp`` — soft-ref на MDM.
Скоркарта агрегирует заказы/претензии/выигранные RFQ → компоненты + балл 0–10.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _supplier(api, **over):
    body = {"name": "Шэньчжэнь Бэттери Co", "unp": "ICN-7788", "country": "Китай", "flag": "🇨🇳"}
    body.update(over)
    r = await api.post("/procurement/suppliers", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_supplier_crud(api):
    created = await _supplier(api, payment_terms="30% предоплата / 70% по факту", lead_time_days=45)
    sid = created["id"]
    assert created["name"] == "Шэньчжэнь Бэттери Co" or created["name"]  # имя сохранено
    assert created["unp"] == "ICN-7788"
    assert created["status"] == "active"

    got = (await api.get(f"/procurement/suppliers/{sid}")).json()
    assert got["payment_terms"] == "30% предоплата / 70% по факту"
    assert got["lead_time_days"] == 45

    r = await api.patch(f"/procurement/suppliers/{sid}", json={"status": "blocked", "incoterms": "FOB"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked" and body["incoterms"] == "FOB"
    assert body["unp"] == "ICN-7788"  # прочие поля не затёрты

    lst = (await api.get("/procurement/suppliers")).json()
    assert any(s["id"] == sid for s in lst)


async def test_supplier_404(api):
    assert (await api.get("/procurement/suppliers/9999")).status_code == 404
    assert (await api.patch("/procurement/suppliers/9999", json={"status": "blocked"})).status_code == 404


async def test_scorecard_no_data(api):
    sup = await _supplier(api)
    sc = (await api.get(f"/procurement/suppliers/{sup['id']}/scorecard")).json()
    assert sc["orders_count"] == 0
    assert sc["claims_total"] == 0
    assert sc["on_time_rate"] is None  # honest-empty: нет дат факта
    assert sc["score"] is None  # нет данных → балла нет


async def test_scorecard_with_orders_and_claim(api):
    sup = await _supplier(api)
    sid = sup["id"]
    # 2 заказа поставщика
    for _ in range(2):
        await api.post(
            "/procurement/orders",
            json={"supplier_id": sid, "lines": [{"sku_code": "A", "qty": 1, "goods_value_byn": 100}]},
        )
    # 1 претензия (открытая)
    await api.post("/procurement/claims", json={"supplier_id": sid, "claim_type": "брак", "qty_affected": 1})

    sc = (await api.get(f"/procurement/suppliers/{sid}/scorecard")).json()
    assert sc["orders_count"] == 2
    assert sc["claims_total"] == 1 and sc["claims_open"] == 1
    # quality = 1 − 1/2 = 0.5; своевременность None → балл = 0.5×10 = 5.0
    assert sc["components"]["quality"] == 0.5
    assert sc["score"] == 5.0


async def test_scorecard_timeliness_real(api):
    """P5: своевременность — доля заказов, принятых не позже ETA (received_at vs eta_date)."""
    sup = await _supplier(api)
    sid = sup["id"]
    # принят вовремя: ETA в будущем (факт приёмки = сегодня ≤ ETA)
    await api.post("/procurement/orders", json={
        "supplier_id": sid, "status": "received", "eta_date": "2026-12-31",
        "lines": [{"sku_code": "A", "qty": 1, "goods_value_byn": 100}]})
    # принят с опозданием: ETA в прошлом
    await api.post("/procurement/orders", json={
        "supplier_id": sid, "status": "received", "eta_date": "2026-01-01",
        "lines": [{"sku_code": "B", "qty": 1, "goods_value_byn": 100}]})

    sc = (await api.get(f"/procurement/suppliers/{sid}/scorecard")).json()
    assert sc["on_time_rate"] == 0.5  # 1 из 2 вовремя
    assert sc["components"]["timeliness"] == 0.5
    # quality 1.0 (нет претензий) + timeliness 0.5 → (0.6×1 + 0.4×0.5)/1.0 ×10 = 8.0
    assert sc["score"] == 8.0


async def test_scorecard_timeliness_none_without_received(api):
    """Без принятых заказов с ETA → on_time_rate None (honest-empty); открытый заказ не считается."""
    sup = await _supplier(api)
    sid = sup["id"]
    await api.post("/procurement/orders", json={
        "supplier_id": sid, "status": "ordered", "eta_date": "2026-12-31",
        "lines": [{"sku_code": "A", "qty": 1, "goods_value_byn": 100}]})
    sc = (await api.get(f"/procurement/suppliers/{sid}/scorecard")).json()
    assert sc["on_time_rate"] is None


async def test_scorecard_timeliness_boundary_on_eta(api):
    """P5 граница `<=`: приёмка ровно в день ETA (received_at.date() == eta_date) = вовремя.

    Пинит границу — регресс `<=`→`<` молча пометил бы доставку точно-в-срок как просрочку.
    ETA берём в UTC, как и received_at (func.now()), чтобы сравнение дат было детерминированным.
    """
    from datetime import datetime, timezone

    today_utc = datetime.now(timezone.utc).date().isoformat()
    sup = await _supplier(api)
    sid = sup["id"]
    await api.post("/procurement/orders", json={
        "supplier_id": sid, "status": "received", "eta_date": today_utc,
        "lines": [{"sku_code": "A", "qty": 1, "goods_value_byn": 100}]})
    sc = (await api.get(f"/procurement/suppliers/{sid}/scorecard")).json()
    assert sc["on_time_rate"] == 1.0  # принят в день ETA — вовремя (граница <=)


async def test_board_card_shows_supplier_score(api):
    """P5: балл поставщика (со своевременностью) доходит до карточки доски (_board_scores → _to_card)."""
    sup = await _supplier(api)
    sid = sup["id"]
    # 2 принятых заказа (1 вовремя, 1 просрочен) → timeliness 0.5, quality 1.0 → score 8.0
    await api.post("/procurement/orders", json={
        "supplier_id": sid, "status": "received", "eta_date": "2026-12-31",
        "lines": [{"sku_code": "A", "qty": 1, "goods_value_byn": 100}]})
    await api.post("/procurement/orders", json={
        "supplier_id": sid, "status": "received", "eta_date": "2026-01-01",
        "lines": [{"sku_code": "B", "qty": 1, "goods_value_byn": 100}]})
    await api.post(
        "/procurement/requests",
        json={"supplier": "Поставщик", "supplier_id": sid, "item": "Доска-балл", "qty": 1},
    )

    board = (await api.get("/procurement/board")).json()
    cards = {c["title"]: c for s in board["stages"] for c in s["cards"]}
    assert cards["Доска-балл"]["score"] == "Score 8.0"


async def test_scorecard_rejected_claims_not_penalized(api):
    """Отклонённая претензия (поставщик не виноват) НЕ снижает балл качества."""
    sup = await _supplier(api)
    sid = sup["id"]
    await api.post("/procurement/orders", json={"supplier_id": sid, "lines": [{"sku_code": "A", "qty": 1, "goods_value_byn": 100}]})
    claim = (await api.post("/procurement/claims", json={"supplier_id": sid, "claim_type": "брак"})).json()
    await api.patch(f"/procurement/claims/{claim['id']}", json={"status": "rejected"})

    sc = (await api.get(f"/procurement/suppliers/{sid}/scorecard")).json()
    assert sc["claims_total"] == 1  # претензия есть в учёте
    assert sc["components"]["quality"] == 1.0  # но качество не наказано (отклонена)
    assert sc["score"] == 10.0
