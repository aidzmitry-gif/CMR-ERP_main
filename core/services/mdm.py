"""MDM — качество мастер-данных контрагентов в ядре (дедуп / merge / survivorship).

Сервисный слой shared kernel (НЕ отдельный модуль): живёт рядом с golden record в
``public``. Матчинг — детерминированный по УНП (natural key); fuzzy по имени — Postgres
``pg_trgm`` позже. **survivorship:** непустое значение выигрывает, эталон в приоритете при
конфликте. **merge обратим** (``unmerge``): дубль архивируется и ссылается на эталон, в
реестр пишется alias; расклейка возвращает дубль и убирает alias.

Транзакцию коммитит вызывающий код (роут) — здесь только изменения сессии (§ядро).
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import (
    AuditLog,
    Contact,
    Counterparty,
    CounterpartyAlias,
    CounterpartyUnpConflict,
    SurvivorshipRule,
    lock_counterparty_unps,
)
from core.services import survivorship
from core.services.registry import RegistryError

#: порог похожести имён по умолчанию для fuzzy-кандидатов (0..1); ниже — не предлагаем.
FUZZY_THRESHOLD = 0.6

#: орг-формы и шум, мешающие сравнению имён (убираем перед похожестью).
_NAME_NOISE = re.compile(
    r"\b(ооо|оао|зао|чуп|ип|уп|одо|общество|акционерное|открытое|закрытое|частное|"
    r"unitarnoe|ltd|llc|inc|gmbh)\b",
    re.IGNORECASE,
)


def _normalize_name(name: str) -> str:
    """Привести имя к виду для сравнения: lower, без орг-форм, кавычек и лишних пробелов."""
    s = (name or "").lower().replace("«", " ").replace("»", " ").replace('"', " ")
    s = _NAME_NOISE.sub(" ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()

#: поля контрагента, участвующие в survivorship при слиянии
_SURVIVORSHIP_FIELDS = ("name", "unp")

#: префикс ссылки на контрагента в журнале аудита (``entity_ref``)
AUDIT_ENTITY_PREFIX = "counterparty:"


class CounterpartyWriteError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.status = code, status


class ManualCounterpartyFields(BaseModel):
    """Поддержка: null/пусто очищает optional; IBAN checksum, BIC syntax, без bank lookup."""

    model_config = ConfigDict(extra="forbid", strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    unp: str | None = None
    legal_address: str | None = Field(default=None, max_length=1000)
    registry_status: str | None = Field(default=None, max_length=255)
    bank_name: str | None = Field(default=None, max_length=255)
    bank_account: str | None = Field(default=None, max_length=64)
    bank_bic: str | None = Field(default=None, max_length=32)

    @field_validator("*", mode="before")
    @classmethod
    def clean(cls, value):
        if isinstance(value, str):
            value.encode("utf-8")
            if any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Недопустимый управляющий символ")
            value = value.strip()
            return value or None
        return value

    @field_validator("name")
    @classmethod
    def name_required_if_supplied(cls, value):
        if value is None:
            raise ValueError("Название не может быть пустым")
        return value

    @field_validator("unp")
    @classmethod
    def valid_unp(cls, value):
        if value is not None and not re.fullmatch(r"[0-9]{9}", value):
            raise ValueError("УНП — 9 цифр")
        return value

    @field_validator("bank_bic")
    @classmethod
    def valid_bic(cls, value):
        if value is None:
            return None
        value = value.upper()
        if not re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?", value):
            raise ValueError("BIC должен содержать 8 или 11 допустимых символов")
        return value

    @field_validator("bank_account")
    @classmethod
    def valid_iban(cls, value):
        if value is None:
            return None
        value = value.replace(" ", "").upper()
        if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", value):
            raise ValueError("Нужен IBAN длиной 15–34 символа")
        rearranged = value[4:] + value[:4]
        digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
        if int(digits) % 97 != 1:
            raise ValueError("Неверная контрольная сумма IBAN")
        return value


class CounterpartyContactPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: int | None = Field(default=None, gt=0)
    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=255)
    is_primary: bool | None = None

    @field_validator("full_name", "phone", "email", mode="before")
    @classmethod
    def clean(cls, value):
        return ManualCounterpartyFields.clean(value)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        if value is not None and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Неверный email")
        return value.lower() if value else None

    @field_validator("phone")
    @classmethod
    def phone_text(cls, value):
        # Формат/добавочный номер сохраняем, телефон — строка, не план нумерации стран.
        if value is not None and not any(c.isdigit() for c in value):
            raise ValueError("Телефон должен содержать цифры")
        return value

    @model_validator(mode="after")
    def name_and_primary(self):
        if (self.id is None or "full_name" in self.model_fields_set) and not self.full_name:
            raise ValueError("Нужно имя контактного лица")
        if "is_primary" in self.model_fields_set and self.is_primary is None:
            raise ValueError("is_primary должен быть true или false")
        return self


RegistryField = Literal["name", "unp", "legal_address", "registry_status"]
_REGISTRY_FIELDS = {"name": "name", "unp": "unp", "legal_address": "address", "registry_status": "status"}


class CounterpartyRegistrySelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    unp: str = Field(pattern=r"^[0-9]{9}$")
    fields: list[RegistryField] = Field(min_length=1, max_length=4)
    preview: dict[RegistryField, str]

    @model_validator(mode="after")
    def exact_selection(self):
        if len(set(self.fields)) != len(self.fields) or set(self.preview) != set(self.fields):
            raise ValueError("Предпросмотр должен содержать ровно выбранные поля")
        return self


class CounterpartyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int | None = Field(default=None, gt=0)
    manual: ManualCounterpartyFields = Field(default_factory=ManualCounterpartyFields)
    contacts: list[CounterpartyContactPatch] = Field(default_factory=list, max_length=50)
    registry: CounterpartyRegistrySelection | None = None

    @model_validator(mode="after")
    def no_overlapping_edits(self):
        ids = [c.id for c in self.contacts if c.id is not None]
        if len(ids) != len(set(ids)) or sum(c.is_primary is True for c in self.contacts) > 1:
            raise ValueError("Повтор контакта или несколько основных контактов")
        if self.registry:
            overlap = set(self.registry.fields) & self.manual.model_fields_set - {"unp"}
            if overlap:
                raise ValueError("Поле нельзя одновременно менять вручную и из реестра")
            if "unp" in self.manual.model_fields_set and self.manual.unp != self.registry.unp:
                raise ValueError("УНП ручного ввода и реестра не совпадают")
        return self


async def verified_registry_selection(gateway, selection: CounterpartyRegistrySelection | None) -> dict | None:
    """Сеть до открытия DB-транзакции. Preview браузера только сравниваем, не сохраняем."""
    if selection is None:
        return None
    if gateway is None:
        raise RegistryError("unconfigured", "Реестр МНС не подключён", 503)
    data = await gateway.lookup_strict(selection.unp)
    if data["unp"] != selection.unp or data["source"] not in {"mns_grp", "demo"}:
        raise RegistryError("invalid_upstream", "Реестр вернул некорректные данные", 502)
    try:
        ManualCounterpartyFields.model_validate({
            field: data[_REGISTRY_FIELDS[field]] for field in set(selection.fields) | {"unp"}
        })
    except ValidationError as exc:
        raise RegistryError("invalid_upstream", "Поля реестра не соответствуют формату карточки", 502) from exc
    for field in selection.fields:
        value = data[_REGISTRY_FIELDS[field]]
        if value != selection.preview[field]:
            raise CounterpartyWriteError("registry_changed", "Данные реестра изменились. Получите новый предпросмотр")
        if not value:
            raise CounterpartyWriteError("registry_field_missing", "Выбранное поле отсутствует в реестре", 422)
    return data


def _contact_dict(contact: Contact) -> dict:
    return {key: getattr(contact, key) for key in ("id", "full_name", "phone", "email", "is_primary")}


async def save_counterparty(
    session: AsyncSession, payload: CounterpartyWrite, *, counterparty_id: int | None,
    registry_data: dict | None, actor: str,
) -> Counterparty:
    """Одна транзакция у вызывающего роута; источник реестра уже проверен до DB I/O."""
    manual = payload.manual.model_dump(exclude_unset=True)
    requested_unp = registry_data["unp"] if registry_data else manual.get("unp")
    if requested_unp:
        await session.run_sync(lambda sync: lock_counterparty_unps(sync, {requested_unp}))
    cp = None
    if counterparty_id is not None:
        cp = (await session.execute(select(Counterparty).where(
            Counterparty.id == counterparty_id,
        ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
        if cp is None:
            raise CounterpartyWriteError("not_found", "Контрагент не найден", 404)
        if not cp.is_active or cp.merged_into_id is not None:
            raise CounterpartyWriteError("archived", "Редактирование архивной записи недоступно")
        if cp.revision != payload.expected_revision:
            raise CounterpartyWriteError("stale_revision", "Карточка изменена. Обновите данные")
        if registry_data and cp.unp and cp.unp != requested_unp and manual.get("unp") != requested_unp:
            raise CounterpartyWriteError("unp_mismatch", "Подтвердите смену УНП вручную", 422)
    if registry_data and (cp is None or not cp.unp) and (
        "unp" not in payload.registry.fields and manual.get("unp") != requested_unp
    ):
        raise CounterpartyWriteError("unp_confirmation_required", "Подтвердите назначение УНП выбранным полем или ручным вводом", 422)
    effective_unp = requested_unp if (registry_data or "unp" in manual) else (cp.unp if cp else None)
    if effective_unp:
        ids = list((await session.scalars(select(Counterparty.id).where(
            func.trim(Counterparty.unp) == effective_unp, Counterparty.is_active.is_(True),
            Counterparty.id != counterparty_id if counterparty_id is not None else True,
        ))).all())
        if ids:
            raise CounterpartyUnpConflict(ids)
    contacts = list((await session.scalars(select(Contact).where(
        Contact.counterparty_id == counterparty_id,
    ))).all()) if cp else []
    by_id = {contact.id: contact for contact in contacts}
    if any(p.id is not None and p.id not in by_id for p in payload.contacts):
        raise CounterpartyWriteError("contact_not_owned", "Контакт не принадлежит этой компании", 422)
    before = None if cp is None else {
        "name": cp.name, "unp": cp.unp, "requisites": deepcopy(cp.requisites or {}),
        "provenance": deepcopy(cp.provenance or {}),
        "contacts": [_contact_dict(c) for c in contacts],
    }
    rules = await survivorship.load_rules(session, "counterparty") if registry_data else {}
    if cp is None:
        name = manual.get("name") or (registry_data["name"] if registry_data and "name" in payload.registry.fields else None)
        if not name:
            raise CounterpartyWriteError("name_required", "Нужно название компании", 422)
        cp = Counterparty(name=name, unp=effective_unp, provenance={}, requisites={})
        session.add(cp)
    provenance = dict(cp.provenance or {})
    requisites = dict(cp.requisites or {})
    now = datetime.now(UTC).isoformat()
    for field, value in manual.items():
        current = getattr(cp, field) if field in {"name", "unp"} else requisites.get(field)
        if current != value or provenance.get(field, {}).get("source") != "manual":
            if field in {"name", "unp"}:
                setattr(cp, field, value)
            else:
                requisites[field] = value
            provenance[field] = {"source": "manual", "at": now}
    if registry_data:
        registry_fields = list(payload.registry.fields)
        for field in registry_fields:
            rule = survivorship.rule_for(rules, field)
            if rule.strategy == "manual_only":
                raise CounterpartyWriteError("protected_field", "Поле закреплено за ручным вводом")
            value = registry_data[_REGISTRY_FIELDS[field]]
            current = getattr(cp, field) if field in {"name", "unp"} else requisites.get(field)
            if field in rules and not survivorship.is_empty(current):
                incoming = survivorship.FieldValue(value, registry_data["source"], registry_data["fetched_at"])
                current_prov = provenance.get(field, {})
                winner = survivorship.decide(
                    survivorship.FieldValue(current, current_prov.get("source", "manual"), current_prov.get("at")),
                    incoming, rule,
                )
                if winner is not incoming and (current != value or current_prov.get("source") != incoming.source):
                    raise CounterpartyWriteError("protected_field", "Выбранное поле защищено правилом источников")
            # Явное применение выбранных полей может заменить manual; произвольный синк — нет.
            if current != value or provenance.get(field, {}).get("source") != registry_data["source"]:
                if field in {"name", "unp"}:
                    setattr(cp, field, value)
                else:
                    requisites[field] = value
                provenance[field] = {"source": registry_data["source"], "at": registry_data["fetched_at"],
                                     "source_url": registry_data["source_url"]}
    cp.provenance, cp.requisites = provenance, requisites
    if counterparty_id is None:
        await session.flush()  # ID нужен для FK контактов; это ещё не commit.
    contacts_changed = False
    for patch in payload.contacts:
        values = patch.model_dump(exclude_unset=True, exclude={"id"})
        contact = by_id.get(patch.id) if patch.id is not None else None
        if contact is None:
            contact = Contact(counterparty_id=cp.id, full_name=patch.full_name, is_primary=False)
            session.add(contact)
            contacts.append(contact)
            contacts_changed = True
        if patch.is_primary:
            for other in contacts:
                if other is not contact and other.is_primary:
                    other.is_primary = False
                    contacts_changed = True
        for key, value in values.items():
            if getattr(contact, key) != value:
                setattr(contact, key, value)
                contacts_changed = True
    if contacts_changed:
        cp.provenance = {**cp.provenance, "contacts": {"source": "manual", "at": now}}
    await session.flush()
    after = {"name": cp.name, "unp": cp.unp, "requisites": dict(cp.requisites or {}),
             "provenance": deepcopy(cp.provenance or {}),
             "contacts": [_contact_dict(c) for c in contacts]}
    if before != after:
        session.add(AuditLog(actor=actor, action="counterparty.created" if before is None else "counterparty.updated",
                             entity_ref=_entity_ref(cp.id), detail={"before": before, "after": after, "revision": cp.revision}))
    return cp


async def duplicate_clusters(session: AsyncSession) -> list[dict]:
    """Кластеры активных контрагентов с одинаковым УНП — кандидаты на слияние."""
    dup_unp_query = (
        select(Counterparty.unp)
        .where(Counterparty.is_active.is_(True), Counterparty.unp.is_not(None))
        .group_by(Counterparty.unp)
        .having(func.count() > 1)
    )
    unps = (await session.execute(dup_unp_query)).scalars().all()
    clusters: list[dict] = []
    for unp in unps:
        rows = (
            await session.execute(
                select(Counterparty)
                .where(Counterparty.unp == unp, Counterparty.is_active.is_(True))
                .order_by(Counterparty.id)
            )
        ).scalars().all()
        clusters.append(
            {"unp": unp, "members": [{"id": r.id, "name": r.name} for r in rows]}
        )
    return clusters


async def import_preview(session: AsyncSession, onec) -> dict:
    """Dry-run предпросмотр импорта контрагентов из кэша 1С в MDM — БЕЗ записи (REF3-9).

    Читает кэш 1С через фасад (``onec.fetch_counterparties`` — только чтение) и считает, сколько
    записей при реальном прогоне СОЗДАЛОСЬ БЫ / совпало по УНП с активным эталоном / без УНП
    (нельзя детерминированно сматчить). Матч — по УНП (natural key), как ``match_candidates``.
    НИЧЕГО не пишет: реальный upsert/дедуп — зона Синк (``reference_import``), здесь только метрика
    готовности моста (мост ~4109 контрагентов сейчас откачен). Возврат:
    ``{total, would_create, would_match_by_unp, without_unp}``.
    """
    cache = await onec.fetch_counterparties()
    existing_unps = {
        u
        for (u,) in (
            await session.execute(
                select(Counterparty.unp).where(
                    Counterparty.is_active.is_(True), Counterparty.unp.is_not(None)
                )
            )
        ).all()
    }
    total = would_create = would_match = without_unp = 0
    for rec in cache:
        total += 1
        unp = (rec.get("unp") or rec.get("УНП") or "").strip() if isinstance(rec, dict) else ""
        if not unp:
            without_unp += 1
        elif unp in existing_unps:
            would_match += 1
        else:
            would_create += 1
    return {
        "total": total,
        "would_create": would_create,
        "would_match_by_unp": would_match,
        "without_unp": without_unp,
    }


def _phone_tail(phone: str | None) -> str:
    """Значащий хвост телефона (9 цифр) — контакты бывают без кода страны; <7 цифр → пропуск.

    Дублирует ``modules.leads.leads.phone_tail`` намеренно: MDM — shared kernel и не должен
    зависеть от модуля. Дедуп контактов по хвосту, как и в лидах/телефонии.
    """
    tail = re.sub(r"\D", "", phone or "")[-9:]
    return tail if len(tail) >= 7 else ""


async def find_contact(
    session: AsyncSession, *, phone: str | None = None, email: str | None = None
) -> Contact | None:
    """Контактное лицо по телефону (хвост 9 цифр) или e-mail (регистронезависимо), либо None.

    Единая точка поиска контакта для дедупа входящего лида против существующих клиентов
    (Цикл 10) и привязки контакта к компании без дублей (Цикл 11). E-mail — точное
    сравнение в нижнем регистре (в LIKE ``_``/``%`` — wildcard'ы), телефон — LIKE по хвосту
    (форматы ``+375…``/``80…`` сходятся). Возвращает первый активный матч.
    """
    email_n = (email or "").strip().lower()
    tail = _phone_tail(phone)
    conds = []
    if tail:
        conds.append(and_(Contact.phone.isnot(None), Contact.phone.like(f"%{tail}")))
    if email_n:
        conds.append(and_(Contact.email.isnot(None), func.lower(Contact.email) == email_n))
    if not conds:
        return None
    return (await session.execute(select(Contact).where(or_(*conds)))).scalars().first()


async def link_contact(
    session: AsyncSession,
    counterparty_id: int,
    *,
    full_name: str,
    phone: str | None = None,
    email: str | None = None,
    is_primary: bool = False,
) -> tuple[Contact, bool]:
    """Привязать контактное лицо к контрагенту БЕЗ дублей (get-or-create). → (contact, created).

    Единая точка добавления контакта в компанию (Цикл 11): если под этим контрагентом уже
    есть контакт с тем же телефоном (хвост 9 цифр) или e-mail — возвращаем его (``created=False``),
    дозаполняя пустые поля (survivorship-lite: непустое не затираем). Иначе создаём новый.
    Дедуп ограничен рамками контрагента (в отличие от глобального ``find_contact``), чтобы
    один и тот же телефон у разных компаний не склеивался. Транзакцию коммитит вызывающий код.
    """
    email_n = (email or "").strip().lower()
    tail = _phone_tail(phone)
    conds = []
    if tail:
        conds.append(and_(Contact.phone.isnot(None), Contact.phone.like(f"%{tail}")))
    if email_n:
        conds.append(and_(Contact.email.isnot(None), func.lower(Contact.email) == email_n))
    existing = None
    if conds:
        existing = (
            await session.execute(
                select(Contact).where(Contact.counterparty_id == counterparty_id, or_(*conds))
            )
        ).scalars().first()
    if existing is not None:
        if not existing.full_name and full_name:
            existing.full_name = full_name
        if not existing.phone and phone:
            existing.phone = phone
        if not existing.email and email:
            existing.email = email
        return existing, False
    contact = Contact(
        counterparty_id=counterparty_id,
        full_name=full_name or "",
        phone=phone or None,
        email=email or None,
        is_primary=is_primary,
    )
    session.add(contact)
    await session.flush()
    return contact, True


async def match_candidates(
    session: AsyncSession, *, unp: str | None, exclude_id: int | None = None
) -> list[Counterparty]:
    """Активные контрагенты с тем же УНП (детерминированный матч).

    Fuzzy-сопоставление по имени (опечатки/регистр) — через Postgres ``pg_trgm`` отдельной
    итерацией; здесь только точный natural key.
    """
    if not unp:
        return []
    query = select(Counterparty).where(
        Counterparty.unp == unp, Counterparty.is_active.is_(True)
    )
    if exclude_id is not None:
        query = query.where(Counterparty.id != exclude_id)
    return list((await session.execute(query)).scalars().all())


async def fuzzy_candidates(
    session: AsyncSession,
    *,
    name: str,
    exclude_id: int | None = None,
    threshold: float = FUZZY_THRESHOLD,
    limit: int = 10,
) -> list[dict]:
    """Похожие по имени активные контрагенты — кандидаты на дедуп (опечатки/регистр/орг-форма).

    Ловит дубли БЕЗ совпадения УНП (пустой/кривой УНП), которые ``match_candidates`` пропускает.
    Это **кандидаты на approval, не авто-merge** — человек-в-контуре решает (концепция §7.2).
    На Postgres — ``pg_trgm`` (``similarity``, расширение в миграции 0046); на SQLite (dev/тесты)
    — Python-фолбэк (``difflib`` над нормализованными именами). ``[{id, name, score}]`` по убыванию.

    # ponytail: (1) ``threshold`` — общий для двух разных шкал (pg_trgm similarity vs
    # SequenceMatcher.ratio), recall на SQLite и Postgres слегка расходится; калибровать порог
    # отдельно по движку, если важна точность. (2) SQLite-фолбэк сканирует все активные имена
    # в Python (O(n)) — ок на dev-объёмах; на проде работает Postgres-ветка с SQL-фильтром.
    """
    norm = _normalize_name(name)
    if not norm:
        return []
    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"

    if dialect == "postgresql":
        sim = func.similarity(func.lower(Counterparty.name), name.lower())
        query = (
            select(Counterparty.id, Counterparty.name, sim.label("score"))
            .where(Counterparty.is_active.is_(True), sim >= threshold)
            .order_by(sim.desc())
            .limit(limit)
        )
        if exclude_id is not None:
            query = query.where(Counterparty.id != exclude_id)
        rows = (await session.execute(query)).all()
        return [{"id": r.id, "name": r.name, "score": float(r.score)} for r in rows]

    # SQLite-фолбэк: тянем активные имена и считаем похожесть в Python (dev-объёмы малы).
    q = select(Counterparty.id, Counterparty.name).where(Counterparty.is_active.is_(True))
    if exclude_id is not None:
        q = q.where(Counterparty.id != exclude_id)
    scored = [
        {"id": cid, "name": cname,
         "score": SequenceMatcher(None, norm, _normalize_name(cname)).ratio()}
        for cid, cname in (await session.execute(q)).all()
    ]
    scored = [s for s in scored if s["score"] >= threshold]
    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored[:limit]


def _apply_survivorship(survivor: Counterparty, duplicate: Counterparty) -> None:
    """Непустое значение выигрывает; эталон в приоритете при конфликте (заполняем пустое).

    Дефолт при merge (стратегия ``non_empty_wins``). Правила-как-данные применяются на пути
    импорта (``reference_import`` + ``survivorship``); при ручном merge дублей эталон в
    приоритете — расширить до загрузки правил можно, когда появятся не-``non_empty_wins``
    поля, конфликтующие именно при слиянии (YAGNI).
    """
    for field in _SURVIVORSHIP_FIELDS:
        if not getattr(survivor, field) and getattr(duplicate, field):
            setattr(survivor, field, getattr(duplicate, field))
            provenance = dict(survivor.provenance or {})
            provenance.pop(field, None)
            if field in (duplicate.provenance or {}):
                provenance[field] = dict(duplicate.provenance[field])
            survivor.provenance = provenance


def _entity_ref(counterparty_id: int) -> str:
    """Ссылка на контрагента в аудите/событиях — формат ``counterparty:<id>``."""
    return f"{AUDIT_ENTITY_PREFIX}{counterparty_id}"


async def merge(
    session: AsyncSession, event_bus, survivor_id: int, duplicate_id: int, *, by: str = ""
) -> Counterparty:
    """Слить ``duplicate`` в ``survivor``: survivorship + архив дубля + alias. Обратимо.

    Пишет доменное событие ``counterparty.merged`` в outbox (та же транзакция) —
    relay проецирует его в ``AuditLog`` по ``entity_ref=counterparty:<survivor_id>``,
    наполняя историю изменений карточки эталона.
    """
    if survivor_id == duplicate_id:
        raise ValueError("нельзя слить запись саму с собой")
    survivor = await session.get(Counterparty, survivor_id)
    duplicate = await session.get(Counterparty, duplicate_id)
    if survivor is None or duplicate is None:
        raise ValueError("контрагент не найден")
    if duplicate.merged_into_id is not None:
        raise ValueError("дубль уже слит")
    _apply_survivorship(survivor, duplicate)
    duplicate.is_active = False
    duplicate.merged_into_id = survivor_id
    session.add(
        CounterpartyAlias(counterparty_id=survivor_id, source="merge", external_ref=str(duplicate_id))
    )
    event_bus.emit(
        session,
        "counterparty.merged",
        {"entity_ref": _entity_ref(survivor_id), "by": by,
         "survivor_id": survivor_id, "duplicate_id": duplicate_id, "duplicate_name": duplicate.name},
    )
    return survivor


async def unmerge(
    session: AsyncSession, event_bus, duplicate_id: int, *, by: str = ""
) -> Counterparty:
    """Расклеить ранее слитый дубль: вернуть активность, снять ссылку, убрать merge-alias.

    Событие ``counterparty.unmerged`` уходит в аудит эталона, из которого расклеили.
    """
    duplicate = await session.get(Counterparty, duplicate_id)
    if duplicate is None or duplicate.merged_into_id is None:
        raise ValueError("запись не является слитым дублем")
    survivor_id = duplicate.merged_into_id
    alias = (
        await session.execute(
            select(CounterpartyAlias).where(
                CounterpartyAlias.source == "merge",
                CounterpartyAlias.external_ref == str(duplicate_id),
            )
        )
    ).scalars().first()
    if alias is not None:
        await session.delete(alias)
    duplicate.is_active = True
    duplicate.merged_into_id = None
    event_bus.emit(
        session,
        "counterparty.unmerged",
        {"entity_ref": _entity_ref(survivor_id), "by": by,
         "survivor_id": survivor_id, "duplicate_id": duplicate_id, "duplicate_name": duplicate.name},
    )
    return duplicate


async def add_source_alias(
    session: AsyncSession, counterparty_id: int, source: str, external_ref: str
) -> CounterpartyAlias:
    """Привязать внешний идентификатор источника (1С/Bitrix) к эталону."""
    alias = CounterpartyAlias(
        counterparty_id=counterparty_id, source=source, external_ref=external_ref
    )
    session.add(alias)
    return alias


async def aliases(session: AsyncSession, counterparty_id: int) -> list[CounterpartyAlias]:
    """Все алиасы/источники эталонной записи."""
    return list(
        (
            await session.execute(
                select(CounterpartyAlias).where(
                    CounterpartyAlias.counterparty_id == counterparty_id
                )
            )
        ).scalars().all()
    )


async def counterparty_card(session: AsyncSession, counterparty_id: int) -> dict | None:
    """Карточка эталона контрагента: реквизиты + источники (alias) + слитые дубли + контакты + аудит.

    Витрина одной записи golden record: откуда она пришла (1С/Bitrix), какие дубли в неё
    слиты (обратимо), кто контактные лица и история изменений (проекция событий по
    ``entity_ref = counterparty:<id>``). ``None`` — записи нет.
    """
    cp = await session.get(Counterparty, counterparty_id)
    if cp is None:
        return None

    alias_rows = await aliases(session, counterparty_id)
    merged = (
        await session.execute(
            select(Counterparty)
            .where(Counterparty.merged_into_id == counterparty_id)
            .order_by(Counterparty.id)
        )
    ).scalars().all()
    contacts = (
        await session.execute(
            select(Contact)
            .where(Contact.counterparty_id == counterparty_id)
            .order_by(Contact.is_primary.desc(), Contact.id)
        )
    ).scalars().all()
    audit = (
        await session.execute(
            select(AuditLog)
            .where(AuditLog.entity_ref == f"{AUDIT_ENTITY_PREFIX}{counterparty_id}")
            .order_by(AuditLog.id.desc())
            .limit(50)
        )
    ).scalars().all()

    return {
        "id": cp.id,
        "name": cp.name,
        "unp": cp.unp,
        "is_active": cp.is_active,
        "merged_into_id": cp.merged_into_id,
        "requisites": cp.requisites or {},
        "revision": cp.revision,
        # M2: происхождение по полям {field: {source, at}} — карточка рисует бейдж источника
        "provenance": cp.provenance or {},
        "aliases": [
            {"source": a.source, "external_ref": a.external_ref, "created_at": str(a.created_at)}
            for a in alias_rows
        ],
        "merged_duplicates": [{"id": d.id, "name": d.name, "unp": d.unp} for d in merged],
        "contacts": [
            {"id": c.id, "full_name": c.full_name, "phone": c.phone,
             "email": c.email, "is_primary": c.is_primary}
            for c in contacts
        ],
        "audit": [
            {"id": a.id, "ts": str(a.ts), "actor": a.actor, "action": a.action, "detail": a.detail}
            for a in audit
        ],
    }


async def survivorship_rules(session: AsyncSession, entity_type: str | None = None) -> list[dict]:
    """Правила слияния (survivorship) — какое поле за каким источником закреплено (M2).

    Витрина таблицы ``survivorship_rule``: для каждой пары (сущность, поле) — стратегия и,
    для ``source_priority``, упорядоченный список источников. Поля без своей записи берут
    дефолт ``non_empty_wins`` (его на витрине не показываем — правил для него нет в БД).
    ``entity_type`` фильтрует (counterparty/sku); пусто — все. Только чтение.
    """
    query = select(SurvivorshipRule).order_by(
        SurvivorshipRule.entity_type, SurvivorshipRule.field
    )
    if entity_type:
        query = query.where(SurvivorshipRule.entity_type == entity_type)
    rows = (await session.execute(query)).scalars().all()
    return [
        {
            "id": r.id,
            "entity_type": r.entity_type,
            "field": r.field,
            "strategy": r.strategy,
            "source_priority": list(r.source_priority or []),
        }
        for r in rows
    ]
