"""A CRM document draft keeps a scoped, conflict-safe field history."""

from core.domain.models import Counterparty
from modules.sales.models import DealDocument


async def test_draft_terms_save_and_history(api, session):
    buyer = Counterparty(name="Покупатель")
    session.add(buyer)
    await session.commit()
    created = await api.post("/sales/deals", json={
        "number": "HIST-DOC-1", "title": "Поставка", "counterparty": "Покупатель",
        "counterparty_id": buyer.id,
    })
    assert created.status_code == 201, created.text
    deal = created.json()
    doc = DealDocument(deal_id=deal["id"], kind="contract", number="DOG-HIST-DOC-1",
                       status="draft")
    session.add(doc)
    await session.commit()
    listed = (await api.get(f"/sales/deals/{deal['id']}/documents")).json()
    assert len(listed) == 1
    original = listed[0]
    assert original["number"] == "DOG-HIST-DOC-1"
    assert len(original["draft_edit_token"]) == 64
    path = f"/sales/documents/{doc.id}"
    assert (await api.patch(f"{path}/draft", json={"payment_terms": "30 дней"})).status_code == 428
    changed = await api.patch(f"{path}/draft", json={
        "expected_edit_token": original["draft_edit_token"],
        "payment_terms": "30 дней", "delivery_terms": "Минск",
    })
    assert changed.status_code == 200, changed.text
    saved = changed.json()
    assert saved["payment_terms"] == "30 дней" and saved["delivery_terms"] == "Минск"
    assert saved["draft_edit_token"] != original["draft_edit_token"]
    stale = await api.patch(f"{path}/draft", json={
        "expected_edit_token": original["draft_edit_token"], "payment_terms": "Неверно",
    })
    assert stale.status_code == 409
    assert (await api.patch(f"{path}/draft", json={
        "expected_edit_token": saved["draft_edit_token"], "payment_terms": "30 дней",
    })).status_code == 200
    history = (await api.get(f"{path}/field-history")).json()
    assert history["document_id"] == doc.id and len(history["items"]) == 1
    row = history["items"][0]
    assert row["actor"] and row["changed_at"] and row["document_number"] == doc.number
    assert row["organization_id"] is None
    assert row["changes"] == {
        "payment_terms": {"before": None, "after": "30 дней"},
        "delivery_terms": {"before": None, "after": "Минск"},
    }
    doc.status = "issued"
    await session.commit()
    assert (await api.patch(f"{path}/draft", json={
        "expected_edit_token": saved["draft_edit_token"], "payment_terms": "После выпуска",
    })).status_code == 409
    assert (await api.get(f"{path}/field-history")).json()["items"] == [row]
