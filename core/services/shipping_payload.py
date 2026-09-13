"""Shared producer/consumer wire contract; never an authorization proof."""

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.services.logistics import ExactInvoiceIdentity

Text255 = Annotated[str, Field(max_length=255)]
Text128 = Annotated[str, Field(max_length=128)]
Money = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)\.[0-9]{2}$", max_length=16)]


class StrictShippingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ShippingIntent(StrictShippingModel):
    mode: Literal["spot", "contract"]
    customer: Text255
    cargo: Text255
    weight_kg: Money
    declared_value_byn: Money
    route_from: Text128
    route_to: Text128
    address: Text255
    zone_code: Annotated[str, Field(max_length=8)]
    carrier_code: Annotated[str, Field(max_length=32)]
    carrier_name: Text128
    pickup_date: Annotated[str, Field(max_length=10)]
    contact: Text255
    comment: Annotated[str, Field(max_length=2000)]

    @field_validator("weight_kg", "declared_value_byn")
    @classmethod
    def numeric_range(cls, value, info):
        bound = (
            Decimal("10000000000") if info.field_name == "weight_kg" else Decimal("1000000000000")
        )
        if Decimal(value) >= bound:
            raise ValueError("Shipping number exceeds storage range")
        return value

    @field_validator("pickup_date")
    @classmethod
    def valid_date(cls, value):
        if value and date.fromisoformat(value).isoformat() != value:
            raise ValueError("Expected YYYY-MM-DD")
        return value


class ShippingSourceIdentity(StrictShippingModel):
    kind: Literal["order", "office"]
    key: Annotated[str, Field(min_length=1, max_length=200)]
    revision: Annotated[str, Field(pattern=r"^[1-9][0-9]*$", max_length=80)]


class ShippingSourceRefs(StrictShippingModel):
    document_id: Annotated[int, Field(gt=0)]
    document_number: Annotated[str, Field(max_length=64)]
    log_ref: Annotated[str, Field(max_length=64)]


class ShippingPayload(StrictShippingModel):
    schema_version: Literal[1]
    source: ShippingSourceIdentity
    source_refs: ShippingSourceRefs
    intent: ShippingIntent

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError("Schema version must be an integer")
        return value

    @model_validator(mode="after")
    def source_key_matches(self):
        if self.source.kind == "order":
            if self.source.key != f"sales:order:{self.source_refs.document_id}":
                raise ValueError("Order key must identify the source document")
        else:
            from uuid import UUID

            prefix = "office:shipping-request:"
            if not self.source.key.startswith(prefix):
                raise ValueError("Office key must identify a shipping request")
            value = self.source.key[len(prefix) :]
            if str(UUID(value)) != value or self.source.revision != "1":
                raise ValueError("Office request requires canonical UUID and revision 1")
        return self


def canonical_hash(value: dict) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_shipping_payload(value: dict) -> tuple[ShippingPayload, str]:
    if not isinstance(value, dict):
        raise ValueError("Shipping payload must be an object")
    # These transport fields never affect promotion or confer trust.
    excluded = {
        "transport_message_id",
        "transport_attempt",
        "transport_received_at",
        "payload_sha256",
    }
    model = ShippingPayload.model_validate({k: v for k, v in value.items() if k not in excluded})
    return model, canonical_hash(model.model_dump(mode="json"))


def shipping_intent_digest(
    exact_invoice: ExactInvoiceIdentity | dict, intent: ShippingIntent | dict
) -> str:
    exact = ExactInvoiceIdentity.model_validate(exact_invoice)
    intent = ShippingIntent.model_validate(intent)
    return canonical_hash(
        {"schema_version": 1, "exact_invoice": exact.model_dump(), "intent": intent.model_dump()}
    )
