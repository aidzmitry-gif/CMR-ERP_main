"""Producer wire values are exact, complete, and independently hashed."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from core.services.shipping_payload import canonical_shipping_payload, shipping_intent_digest


def payload():
    return {
        "schema_version": 1,
        "source": {"kind": "order", "key": "sales:order:7", "revision": "1"},
        "source_refs": {"document_id": 7, "document_number": "O7", "log_ref": ""},
        "intent": {
            "mode": "spot",
            "customer": "Получатель",
            "cargo": "Товар",
            "weight_kg": "2.00",
            "declared_value_byn": "100.00",
            "route_from": "W",
            "route_to": "Минск",
            "address": "Адрес",
            "zone_code": "z1",
            "carrier_code": "dpd",
            "carrier_name": "DPD",
            "pickup_date": "2026-09-11",
            "contact": "Контакт",
            "comment": "",
        },
    }


def test_payload_hash_is_computed_not_embedded_and_preserves_references():
    original = payload()
    _, digest = canonical_shipping_payload(original)
    with_transport = {**original, "payload_sha256": "forged", "transport_attempt": 9}
    assert canonical_shipping_payload(with_transport)[1] == digest
    changed = deepcopy(with_transport)
    changed["intent"]["cargo"] = "Changed"
    assert canonical_shipping_payload(changed)[1] != digest
    changed = deepcopy(original)
    changed["source_refs"]["document_number"] = "Changed"
    assert canonical_shipping_payload(changed)[1] != digest


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_schema_requires_integer(value):
    data = payload()
    data["schema_version"] = value
    with pytest.raises(ValidationError):
        canonical_shipping_payload(data)


@pytest.mark.parametrize(
    "value", ["NaN", "Infinity", "-1.00", "1", "1.001", "1e2", 1.0, True, "01.00", "10000000000.00"]
)
def test_weight_requires_exact_bounded_decimal_string(value):
    data = payload()
    data["intent"]["weight_kg"] = value
    with pytest.raises(ValidationError):
        canonical_shipping_payload(data)


@pytest.mark.parametrize("mutation", ["unknown", "missing", "bool_id", "wrong_key", "bad_date"])
def test_complete_unambiguous_source(mutation):
    data = payload()
    if mutation == "unknown":
        data["company"] = "Alias"
    elif mutation == "missing":
        del data["intent"]["address"]
    elif mutation == "bool_id":
        data["source_refs"]["document_id"] = True
    elif mutation == "wrong_key":
        data["source"]["key"] = "sales:order:8"
    else:
        data["intent"]["pickup_date"] = "2026-02-30"
    with pytest.raises(ValidationError):
        canonical_shipping_payload(data)


def test_execution_digest_links_only_same_exact_invoice_and_intent():
    model, _ = canonical_shipping_payload(payload())
    exact = {
        "organization_id": 1,
        "document_id": 2,
        "expected_version": 1,
        "expected_content_sha256": "a" * 64,
    }
    digest = shipping_intent_digest(exact, model.intent)
    assert digest == shipping_intent_digest(exact, model.intent.model_dump())
    assert digest != shipping_intent_digest({**exact, "expected_version": 2}, model.intent)
    assert digest != shipping_intent_digest(
        exact, {**model.intent.model_dump(), "route_to": "Other"}
    )


@pytest.mark.parametrize("field", ["route_from", "route_to", "carrier_name"])
def test_intent_fits_actual_target_columns(field):
    data = payload()
    data["intent"][field] = "x" * 128
    canonical_shipping_payload(data)
    data["intent"][field] += "x"
    with pytest.raises(ValidationError):
        canonical_shipping_payload(data)


@pytest.mark.parametrize("value", [None, [], "payload", 1])
def test_payload_top_level_requires_object(value):
    with pytest.raises(ValueError, match="object"):
        canonical_shipping_payload(value)


def test_shipping_dispatcher_registration_and_isolation():
    from fastapi import HTTPException

    from core.services.logistics import ShippingProducerDispatcher

    first, second = ShippingProducerDispatcher(), ShippingProducerDispatcher()
    adapter = object()
    first.register("order", adapter)
    assert first._adapter("order") is adapter
    with pytest.raises(ValueError, match="already registered"):
        first.register("order", object())
    with pytest.raises(ValueError, match="Unsupported"):
        first.register("unknown", adapter)
    with pytest.raises(HTTPException) as missing:
        second._adapter("order")
    assert missing.value.status_code == 409
    with pytest.raises(HTTPException):
        first._adapter("office")


def test_runtime_registers_source_owned_shipping_adapters():
    from core.runtime.app import create_app
    from modules.office.shipping_producer import OfficeShippingProducer
    from modules.sales.shipping_producer import SalesShippingProducer

    app = create_app()
    core = app.state.core
    dispatcher = core.services.shipping_producer
    order = dispatcher._adapter("order")
    office = dispatcher._adapter("office")
    assert isinstance(order, SalesShippingProducer)
    assert isinstance(office, OfficeShippingProducer)
    assert order.core is core and office.core is core
