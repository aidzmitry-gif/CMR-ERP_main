"""Общее ядро (shared kernel) — ORM-модели сущностей, нужных всем модулям.

Контрагент, контакт, SKU/номенклатура и пользователь живут здесь, и все модули
читают их через ядро, а не дублируют у себя (§2.4). Таблицы — в схеме по умолчанию
(``public``); таблицы модулей живут в собственных схемах.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class Counterparty(Base):
    """Контрагент (клиент или поставщик) — эталонная запись (golden record).

    Дубли склеиваются MDM-сервисом ядра (``core.services.mdm``): дубль архивируется
    (``is_active=False``) и ссылается на эталон (``merged_into_id``); merge обратим.
    """

    __tablename__ = "counterparty"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    unp: Mapped[str | None] = mapped_column(String(32))  # УНП (РБ) — natural key
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    # ссылка дубля на эталон, в который он слит (NULL — самостоятельная запись)
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("counterparty.id"))
    # происхождение по полям (field-level provenance): {поле: {"source": ..., "at": ...}}.
    # Источник КАЖДОГО поля, а не записи целиком → survivorship-движок знает, что синк
    # вправе перезаписать, а что закреплено за ЕГР/ERP/ручным вводом (M2 дорожной карты).
    provenance: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class CounterpartyAlias(Base):
    """Алиас/источник эталонной записи контрагента (golden record).

    Привязка внешних идентификаторов (1С, Bitrix) и слитых дублей к эталону. Позволяет
    резолвить ссылки из внешних систем и обратимо расклеивать merge.
    """

    __tablename__ = "counterparty_alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    counterparty_id: Mapped[int] = mapped_column(ForeignKey("counterparty.id"))  # эталон
    source: Mapped[str] = mapped_column(String(32))  # "1c" | "bitrix" | "merge" | "erp"
    external_ref: Mapped[str] = mapped_column(String(128))  # id/код записи в источнике
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SurvivorshipRule(Base):
    """Правило слияния по полю — «кто побеждает» при конфликте источников (M2).

    Survivorship как **данные, а не код**: для пары (сущность, поле) задаётся стратегия и,
    для ``source_priority``, упорядоченный список источников. Применяется при импорте из
    внешних систем и при merge дублей. Поля без своего правила берут дефолт ``non_empty_wins``.
    Так синк из 1С не затирает то, что закреплено за ЕГР/ERP/ручным вводом.
    """

    __tablename__ = "survivorship_rule"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32))  # "counterparty" | "sku" | ...
    field: Mapped[str] = mapped_column(String(64))
    # стратегия: source_priority | manual_only | most_recent | non_empty_wins
    strategy: Mapped[str] = mapped_column(String(32))
    # для source_priority — упорядоченный список источников ["egr","erp","manual","1c","bitrix"]
    source_priority: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")


class SyncLink(Base):
    """Связь записи ERP с внешней системой + статус выгрузки (M3, опция B плана).

    Одна таблица на любую сущность (``entity_type``) и любую внешнюю систему (``system``):
    хранит внешний id (``external_ref``, NULL пока не выгружено), происхождение (``origin``),
    направление и состояние очереди. ``CounterpartyAlias`` остаётся для MDM-провенанса/дедупа,
    а роль «ссылка в 1С + статус выгрузки» — здесь. ERP — система-истина: запись, рождённая
    в ERP (``origin="erp"``), ставится в очередь на выгрузку и доезжает в 1С с подтверждением.
    """

    __tablename__ = "sync_link"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32))  # "counterparty" | "sku"
    entity_id: Mapped[int] = mapped_column()
    system: Mapped[str] = mapped_column(String(32), default="1c", server_default="1c")
    external_ref: Mapped[str | None] = mapped_column(String(128))  # Ref_Key в 1С, NULL до выгрузки
    origin: Mapped[str] = mapped_column(String(16))  # "erp" | "1c" | "bitrix"
    direction: Mapped[str] = mapped_column(String(8), default="out", server_default="out")  # in|out
    # local — только в ERP; pending — в очереди; synced — выгружено; error — ошибка
    state: Mapped[str] = mapped_column(String(16), default="local", server_default="local")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_text: Mapped[str | None] = mapped_column(String(255))


class Contact(Base):
    """Контактное лицо контрагента."""

    __tablename__ = "contact"

    id: Mapped[int] = mapped_column(primary_key=True)
    counterparty_id: Mapped[int | None] = mapped_column(ForeignKey("counterparty.id"))
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(default=False, server_default="false")


class Sku(Base):
    """Единица номенклатуры (товарная позиция) — мастер-данные (golden record).

    ERP — система-источник номенклатуры; код — natural key (не зависит от 1С). «Горячие»
    поля, нужные продавцу/расчёту в момент сделки (вес, ТН ВЭД, срок годности) — типизированные
    колонки; длинный хвост характеристик — в ``attributes`` JSONB (концепция §4.3). Транзакционные
    данные (партии, landed cost, остатки) НЕ здесь — читаются через фасады ядра (CQRS, §6).
    """

    __tablename__ = "sku"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(16), default="шт", server_default="шт")
    # группа (категория) номенклатуры — ссылка на иерархический справочник (public)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("ref_nomenclature_category.id"))
    # «горячие» поля (M4): вес/объём для распределения фрахта, ТН ВЭД для пошлины (→ landed cost),
    # НДС-код (свой ∨ наследуется от группы), срок годности в днях для FEFO-алерта (<1 года).
    # Nullable — заполняются по мере данных.
    weight_kg: Mapped[float | None] = mapped_column()
    volume_m3: Mapped[float | None] = mapped_column()  # объём, м³ — разнесение фрахта по объёму
    tnved_code: Mapped[str | None] = mapped_column(String(16))  # код ТН ВЭД (пошлина из справочника)
    vat_code: Mapped[str | None] = mapped_column(String(16))  # свой код НДС (→ ref_vat_rate); None → от группы
    shelf_life_days: Mapped[int | None] = mapped_column()  # срок годности; None — бессрочно
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")  # архив, не удаление
    # переменные характеристики (цвет/размер упаковки/палета/тех.параметры) — JSONB, не EAV;
    # фасетный поиск млн+ SKU — через внешний search-движок.
    attributes: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    # происхождение по полям (field-level provenance, M2) — единый слой с Counterparty.
    provenance: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class User(Base):
    """Пользователь системы, связанный с сотрудником HR и identity в Keycloak."""

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True)
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    # Мягкая ссылка: ядро не должно иметь FK-зависимость от опционального HR-модуля.
    employee_id: Mapped[int | None] = mapped_column(unique=True)
    department: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str | None] = mapped_column(String(64))
    keycloak_user_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="active", server_default="active")
    invited_at: Mapped[datetime | None] = mapped_column(DateTime)


class OutboxEvent(Base):
    """Журнал доменных событий (transactional outbox).

    Пишется в одной транзакции с изменением состояния (гарантия at-least-once);
    relay доставляет подписчикам и проставляет ``processed_at`` (часть 3).
    Это инфраструктурная таблица ядра.
    """

    __tablename__ = "outbox_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Approval(Base):
    """Запрос на согласование (human-in-the-loop).

    Долгоживущий: висит в БД в ожидании решения человека, переживает рестарт.
    Маршрутизируется по роли (`route`), эскалируется по таймеру (`due_at`).
    Это инфраструктурная таблица ядра (часть 4).
    """

    __tablename__ = "approval"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    entity_ref: Mapped[str] = mapped_column(String(64))  # например "deal:7"
    subject: Mapped[str] = mapped_column(String(255))
    route: Mapped[str] = mapped_column(String(64))  # роль-согласующий
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    requested_by: Mapped[str] = mapped_column(String(128), default="", server_default="")
    decided_by: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(String(255))
    escalation_level: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class AuditLog(Base):
    """Неизменяемый журнал аудита — проекция доменных событий (append-only, часть 5)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    actor: Mapped[str] = mapped_column(String(128), default="", server_default="")
    action: Mapped[str] = mapped_column(String(128))
    entity_ref: Mapped[str] = mapped_column(String(64), default="", server_default="")
    detail: Mapped[dict] = mapped_column(JSON)
