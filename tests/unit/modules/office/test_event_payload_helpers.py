from decimal import Decimal

from modules.office import events


def test_deal_id_accepts_integer_like_values_and_is_honest_on_bad_input():
    assert events._deal_id({"deal_id": 42}) == 42
    assert events._deal_id({"deal_id": " 42 "}) == 42
    assert events._deal_id({}) is None
    assert events._deal_id({"deal_id": ""}) is None
    assert events._deal_id({"deal_id": "not-a-number"}) is None


def test_outstanding_defaults_to_zero_and_preserves_decimal_precision():
    assert events._outstanding({}) == Decimal("0")
    assert events._outstanding({"outstanding": ""}) == Decimal("0")
    assert events._outstanding({"outstanding": "123.4500"}) == Decimal("123.4500")
    assert events._outstanding({"outstanding": "bad"}) == Decimal("0")
