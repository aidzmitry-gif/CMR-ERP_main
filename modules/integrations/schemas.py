"""Pydantic-схемы модуля Integrations."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.services.intake_storage import MAX_B64_CHARS, MAX_SIZE_BYTES


class StockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku_code: str
    warehouse: str
    qty_available: float
    qty_reserved: float
    qty_forecast: float
    price: float
    cost: float | None = None


class RegistryOut(BaseModel):
    """Проверенная карточка ГРП МНС или явно помеченные demo-данные."""

    unp: str
    name: str
    address: str
    status: str
    short_name: str | None = None
    status_code: str | None = None
    registered_at: str | None = None
    closed_at: str | None = None
    source: Literal["mns_grp", "demo"]
    source_url: str | None
    fetched_at: datetime


class OriginateIn(BaseModel):
    """Запрос инициации исходящего звонка: внутренний номер сотрудника + клиент."""

    vnut: str
    number: str


IntakeNamespace = Literal[
    "microchips.by", "enersys.by", "admin@enersys.by", "zakupki.legat.by"
]


class IntakeLeadIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(default="", max_length=255)
    company: str = Field(default="", max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    region: str = Field(default="", max_length=64)
    product: str = Field(default="", max_length=128)
    message: str = Field(default="", max_length=256 * 1024)
    utm_source: str = Field(default="", max_length=128)
    utm_medium: str = Field(default="", max_length=128)
    utm_campaign: str = Field(default="", max_length=128)
    landing_url: str = Field(default="", max_length=2048)

    @field_validator("message")
    @classmethod
    def bounded_text(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 256 * 1024 or "\x00" in value:
            raise ValueError("Недопустимый текст сообщения")
        return value  # Do not truncate or strip the original message.

    @field_validator("phone", "email")
    @classmethod
    def clean_contact(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return (value.lower() if info.field_name == "email" else value) or None


class IntakeFileIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    file_id: str = Field(min_length=1, max_length=128, pattern=r"^[!-~]+$")
    filename: str = Field(min_length=1, max_length=255)
    data_url: str = Field(min_length=1, max_length=MAX_B64_CHARS + 128)
    size_bytes: int = Field(gt=0, le=MAX_SIZE_BYTES)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("filename")
    @classmethod
    def safe_display_name(cls, value: str) -> str:
        value.encode("utf-8")
        if any(ord(c) < 32 or ord(c) == 127 or c in '/\\"' for c in value):
            raise ValueError("Недопустимое имя файла")
        return value


class IntakeRequestIn(BaseModel):
    """One enquiry delivery. A multi-lot email must send one envelope per lot.

    source_id identifies an enquiry, delivery_id an immutable envelope (include
    the lot in an email delivery_id). Mail copies use the site's exact source_id.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    namespace: IntakeNamespace
    identity_namespace: IntakeNamespace | None = None
    source_id: str = Field(min_length=1, max_length=256, pattern=r"^[!-~]+$")
    delivery_id: str = Field(min_length=1, max_length=256, pattern=r"^[!-~]+$")
    lead: IntakeLeadIn
    subject: str = Field(default="", max_length=4096)
    message_id: str = Field(default="", max_length=998)
    source_url: str = Field(default="", max_length=2048)
    template_id: Literal[2344, 2400, 2517] | None = None
    tender_id: str | None = Field(default=None, max_length=96, pattern=r"^[A-Za-z0-9._-]+$")
    lot_id: str | None = Field(default=None, max_length=96, pattern=r"^[A-Za-z0-9._-]+$")
    files: list[IntakeFileIn] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def source_contract(self):
        self.identity_namespace = self.identity_namespace or self.namespace
        if self.identity_namespace != self.namespace and not (
            self.namespace == "admin@enersys.by"
            and self.identity_namespace in {"microchips.by", "enersys.by"}
        ):
            raise ValueError("Недопустимая межканальная связь")
        if self.namespace == "zakupki.legat.by":
            if not self.template_id or not self.tender_id or not self.lot_id:
                raise ValueError("Нужны включённый шаблон, тендер и лот")
            if self.source_id != f"tender:{self.tender_id}:lot:{self.lot_id}":
                raise ValueError("source_id должен однозначно задавать тендер и лот")
        elif any(value is not None for value in (self.template_id, self.tender_id, self.lot_id)):
            raise ValueError("Поля тендера разрешены только для Legat")
        if len({item.file_id for item in self.files}) != len(self.files):
            raise ValueError("Повтор file_id")
        if not any(self.lead.model_dump().values()) and not self.subject and not self.files:
            raise ValueError("Пустое обращение")
        # PostgreSQL text/json cannot store NUL or unpaired Unicode surrogates.
        for value in (*self.lead.model_dump().values(), self.subject, self.message_id, self.source_url):
            if isinstance(value, str):
                value.encode("utf-8")
                if "\x00" in value:
                    raise ValueError("Недопустимый символ текста")
        return self
