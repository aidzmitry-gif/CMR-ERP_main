from decimal import Decimal

from modules.logistics import routes as logistics_routes
from modules.office import routes as office_routes
from modules.office.models import OfficeDoc


def test_office_card_maps_business_fields_and_omits_empty_tags():
    card = office_routes._to_card(
        OfficeDoc(
            id=14,
            number="",
            company="ООО Альфа",
            title="Счёт и УПД",
            amount=Decimal("125.50"),
            delivery="DPD",
            docs_status="Оригиналы отправлены",
            priority="Высокий",
            owner="Офис",
            op_date="2026-09-17",
            next_step="Получить оплату",
        )
    )

    assert card.model_dump() == {
        "id": 14,
        "code": "ДОК-14",
        "title": "ООО Альфа",
        "subtitle": "Счёт и УПД",
        "flag": "",
        "amount": 125.5,
        "priority": "Высокий",
        "status_tag": "",
        "owner": "Офис",
        "date": "2026-09-17",
        "progress": None,
        "next_step": "Получить оплату",
        "insight": "",
        "score": "",
        "state": "",
        "action": "",
        "details": [],
        "tags": ["DPD", "Оригиналы отправлены"],
    }

    empty = office_routes._to_card(
        OfficeDoc(
            id=15,
            number="OFF-15",
            company="",
            title="",
            amount=Decimal("0"),
            priority="",
            owner="",
            next_step="",
        )
    )
    assert (empty.code, empty.amount, empty.tags) == ("OFF-15", 0.0, [])


def test_carrier_name_prefers_catalog_then_own_transport_then_raw_code():
    assert logistics_routes._carrier_name("autolight") == "Автолайт Экспресс"
    assert logistics_routes._carrier_name("own") == "Свой транспорт"
    assert logistics_routes._carrier_name("partner-x") == "partner-x"
