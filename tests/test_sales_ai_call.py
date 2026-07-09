"""SALES-54: AI-скрипт звонка (со-пилот продавца) + подсказки по возражениям."""
from sqlalchemy import select

from modules.sales.models import CallLog, Deal


async def _make_call(session, deal_id=None, call_id="c1"):
    session.add(
        CallLog(call_id=call_id, phone_e164="+375291112233", status="ended", deal_id=deal_id)
    )
    await session.flush()
    return (
        await session.execute(select(CallLog).where(CallLog.call_id == call_id))
    ).scalars().first()


async def test_call_script_static_without_ai(api, session):
    """AI выключен → статичный скрипт (не 503), каркас заполнен, ai_hint=None."""
    call = await _make_call(session)
    r = await api.post(f"/sales/calls/{call.id}/ai/script")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "static" and body["ai_hint"] is None
    assert body["goal"] and body["talking_points"] and body["questions"]
    assert body["stage"] == "new"  # без сделки — вход воронки


async def test_call_script_stage_specific(api, session):
    """Скрипт берёт цель по стадии привязанной сделки."""
    session.add(Deal(number="D-54", title="t", counterparty="ООО Х", stage="contract"))
    await session.flush()
    deal = (await session.execute(select(Deal).where(Deal.number == "D-54"))).scalars().first()
    call = await _make_call(session, deal_id=deal.id, call_id="c2")
    body = (await api.post(f"/sales/calls/{call.id}/ai/script")).json()
    assert body["stage"] == "contract"
    assert "договор" in (body["goal"] + " ".join(body["talking_points"])).lower()


async def test_call_script_with_ai(ai_api, session):
    """AI включён → ai_hint заполнен, источник не статичный."""
    call = await _make_call(session, call_id="c3")
    body = (await ai_api.post(f"/sales/calls/{call.id}/ai/script")).json()
    assert body["ai_hint"] and body["model"] != "static"


async def test_objection_classification(api, session):
    call = await _make_call(session, call_id="c4")
    price = (
        await api.post(f"/sales/calls/{call.id}/ai/objection", json={"objection": "это слишком дорого"})
    ).json()
    assert price["category"] == "price" and price["reply"]
    stock = (
        await api.post(f"/sales/calls/{call.id}/ai/objection", json={"objection": "а этого нет в наличии?"})
    ).json()
    assert stock["category"] == "stock"
    # competitor проверяется раньше price: «у конкурента дешевле» → competitor, не price
    comp = (
        await api.post(f"/sales/calls/{call.id}/ai/objection", json={"objection": "у конкурента дешевле"})
    ).json()
    assert comp["category"] == "competitor"
    other = (
        await api.post(f"/sales/calls/{call.id}/ai/objection", json={"objection": "пришлите реквизиты"})
    ).json()
    assert other["category"] == "other"


async def test_objection_with_ai(ai_api, session):
    call = await _make_call(session, call_id="c5")
    body = (
        await ai_api.post(f"/sales/calls/{call.id}/ai/objection", json={"objection": "дорого"})
    ).json()
    assert body["category"] == "price" and body["ai_hint"]


async def test_call_ai_404(api):
    assert (await api.post("/sales/calls/999/ai/script")).status_code == 404
    assert (
        await api.post("/sales/calls/999/ai/objection", json={"objection": "x"})
    ).status_code == 404
