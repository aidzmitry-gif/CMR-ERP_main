"""Прототип обогащения звонков → база знаний по клиентам (пробный прогон 1-3 звонка).

Конвейер на один звонок:
  1. читаем уже скачанный звонок из data/inbox/*.json (+ mp3 в data/media/);
  2. РЕЗОЛВ: CRM_ENTITY (contact/company) и наш менеджер (PORTAL_USER_ID) → имена из Bitrix;
     upsert в shared-kernel (Counterparty / Contact / User) + CounterpartyAlias(source="bitrix");
  3. ТРАНСКРИПЦИЯ: faster-whisper large-v3 локально (RU), результат — текст;
  4. ЗАПИСЬ: строка в таблицу comm_call (звонок привязан к клиенту/контакту/менеджеру).

Намеренно НЕ модуль `communications`, а отдельный скрипт-прототип: пока формат не устаканен,
не плодим обвязку module.py/регистрацию. Когда формат подтвердится — модель переедет в
modules/communications/. Summary/insights (LLM) — следующий этап, здесь только транскрипт.

Запуск из корня проекта (нужен заполненный connectors/.env с BITRIX_WEBHOOK):
    $env:AIOS_DATABASE_URL = "sqlite:///./dev.db"   # синхронный SQLite для прототипа
    python -m connectors.enrich            # обработать первые 3 звонка из inbox
    python -m connectors.enrich 1          # обработать 1 звонок
"""
from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime

import requests
from sqlalchemy import ForeignKey, String, Text, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from core.db.base import Base
from core.domain.models import Contact, Counterparty, CounterpartyAlias, User

from . import config

# Прототипная таблица звонков. Живёт в той же metadata (Base), создаётся create_all ниже.
# Когда формат устаканится — переедет в modules/communications/models.py со схемой "communications".


class CommCall(Base):
    """Звонок с привязкой к клиенту/контакту/менеджеру и транскриптом (прототип)."""

    __tablename__ = "comm_call"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), default="bitrix")
    external_id: Mapped[str] = mapped_column(String(64))  # ID звонка в Bitrix
    counterparty_id: Mapped[int | None] = mapped_column(ForeignKey("counterparty.id"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contact.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))  # наш менеджер
    direction: Mapped[str | None] = mapped_column(String(8))  # in | out
    phone: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[str | None] = mapped_column(String(32))
    duration_sec: Mapped[int | None] = mapped_column()
    recording_path: Mapped[str | None] = mapped_column(String(255))
    transcript: Mapped[str | None] = mapped_column(Text)
    transcript_lang: Mapped[str | None] = mapped_column(String(8))
    # краткое содержание звонка (заполняет шаг insights, вариант A)
    summary: Mapped[str | None] = mapped_column(Text)
    # тип звонка по содержанию: client | inbound_request | spam | unknown
    call_kind: Mapped[str | None] = mapped_column(String(24))
    # категория звонка (insights): target_client|service_supplier|goods_supplier|non_target|spam|service
    category: Mapped[str | None] = mapped_column(String(24))
    value: Mapped[str | None] = mapped_column(String(8))       # ценность: high|medium|low
    outcome: Mapped[str | None] = mapped_column(Text)          # что менеджер сделал по итогу
    rep_advice: Mapped[str | None] = mapped_column(Text)       # совет продавцу (для целевых)


class CommInsight(Base):
    """Извлечённый из звонка факт (намерение, потребность, договорённость, риск).

    То, на чём ИИ строит рекомендации по клиенту. Заполняется шагом insights (вариант A).
    """

    __tablename__ = "comm_insight"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("comm_call.id"))
    kind: Mapped[str] = mapped_column(String(24))  # intent|need|product|agreement|risk|contact
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="rule")  # rule | llm


# --- резолв через Bitrix (только чтение) ---


def _bx_call(method: str, params: dict) -> dict:
    base = config.BITRIX_WEBHOOK.rstrip("/") + "/"
    resp = requests.post(base + method, json=params, timeout=60)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Bitrix {method}: {data.get('error')} {data.get('error_description')}")
    return data.get("result") or {}


def _alias_lookup(s: Session, model, external_ref: str):
    """Найти уже импортированную сущность по bitrix-алиасу (для контрагента)."""
    if model is Counterparty:
        a = s.scalar(
            select(CounterpartyAlias).where(
                CounterpartyAlias.source == "bitrix",
                CounterpartyAlias.external_ref == external_ref,
            )
        )
        return s.get(Counterparty, a.counterparty_id) if a else None
    return None


def _resolve_counterparty(s: Session, company_id: str) -> Counterparty | None:
    """Компания Bitrix → Counterparty (golden record) + alias. Идемпотентно по алиасу."""
    if not company_id or company_id == "0":
        return None
    existing = _alias_lookup(s, Counterparty, f"company:{company_id}")
    if existing:
        return existing
    info = _bx_call("crm.company.get", {"id": company_id})
    if not info:
        return None
    cp = Counterparty(name=info.get("TITLE") or f"Bitrix company {company_id}",
                      unp=(info.get("UF_CRM_UNP") or None))
    s.add(cp)
    s.flush()
    s.add(CounterpartyAlias(counterparty_id=cp.id, source="bitrix",
                            external_ref=f"company:{company_id}"))
    return cp


def _resolve_contact(s: Session, contact_id: str) -> tuple[Contact | None, Counterparty | None]:
    """Контакт Bitrix → Contact (+ его компания как Counterparty). Идемпотентно по телефону+ФИО."""
    if not contact_id or contact_id == "0":
        return None, None
    info = _bx_call("crm.contact.get", {"id": contact_id})
    if not info:
        return None, None
    full_name = " ".join(x for x in (info.get("NAME"), info.get("LAST_NAME")) if x).strip() \
        or f"Bitrix contact {contact_id}"
    phone = ""
    if info.get("PHONE"):
        phone = (info["PHONE"][0] or {}).get("VALUE", "")
    email = ""
    if info.get("EMAIL"):
        email = (info["EMAIL"][0] or {}).get("VALUE", "")
    # компания контакта
    cp = _resolve_counterparty(s, str(info.get("COMPANY_ID") or "")) if info.get("COMPANY_ID") else None
    # идемпотентность контакта: по ФИО (+ телефон) в рамках контрагента
    existing = s.scalar(select(Contact).where(Contact.full_name == full_name,
                                              Contact.phone == (phone or None)))
    if existing:
        return existing, cp
    c = Contact(counterparty_id=cp.id if cp else None, full_name=full_name,
                phone=phone or None, email=email or None)
    s.add(c)
    s.flush()
    return c, cp


def _resolve_user(s: Session, user_id: str) -> User | None:
    """Сотрудник Bitrix (оператор) → User. Идемпотентно по username=bitrix:<id>."""
    if not user_id:
        return None
    username = f"bitrix:{user_id}"
    existing = s.scalar(select(User).where(User.username == username))
    if existing:
        return existing
    info = _bx_call("user.get", {"ID": user_id})
    rec = info[0] if isinstance(info, list) and info else {}
    full_name = " ".join(x for x in (rec.get("NAME"), rec.get("LAST_NAME")) if x).strip() \
        or f"Bitrix user {user_id}"
    u = User(username=username, full_name=full_name)
    s.add(u)
    s.flush()
    return u


# --- транскрипция (faster-whisper, локально) ---

_model = None


def _transcribe(path: str) -> tuple[str, str]:
    """Распознать запись звонка. Возвращает (текст, язык). Модель грузится один раз."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        # Модель из ASR_MODEL (по умолчанию medium — баланс качество/память на CPU;
        # large-v3 на CPU часто упирается в RAM: mkl_malloc failed).
        name = os.getenv("ASR_MODEL", "medium")
        print(f"  загрузка модели faster-whisper {name} (один раз)...")
        _model = WhisperModel(name, device="cpu", compute_type="int8")
    segments, info = _model.transcribe(path, language="ru", vad_filter=True)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text, info.language


# --- основной конвейер ---

_TYPE_MAP = {"1": "out", "2": "in"}  # CALL_TYPE Bitrix: 1=исходящий, 2=входящий


def process(s: Session, record: dict) -> CommCall:
    p = record["payload"]
    call_id = str(p.get("ID"))
    print(f"\n— звонок ID={call_id} ({p.get('CALL_START_DATE')}, {p.get('CALL_DURATION')}с)")

    # уже обработан?
    if s.scalar(select(CommCall).where(CommCall.source == "bitrix",
                                       CommCall.external_id == call_id)):
        print("  уже в базе — пропуск")
        return None

    entity_type = (p.get("CRM_ENTITY_TYPE") or "").upper()
    entity_id = str(p.get("CRM_ENTITY_ID") or "")
    contact = cp = None
    if entity_type == "CONTACT":
        contact, cp = _resolve_contact(s, entity_id)
    elif entity_type == "COMPANY":
        cp = _resolve_counterparty(s, entity_id)
    manager = _resolve_user(s, str(p.get("PORTAL_USER_ID") or ""))
    print(f"  клиент: {cp.name if cp else '—'} | контакт: {contact.full_name if contact else '—'} "
          f"| менеджер: {manager.full_name if manager else '—'}")

    transcript = lang = None
    media = record.get("media_path")
    if media and os.path.exists(media):
        transcript, lang = _transcribe(media)
        preview = (transcript[:160] + "…") if transcript and len(transcript) > 160 else transcript
        print(f"  транскрипт ({lang}): {preview or '(пусто)'}")
    else:
        print("  записи нет — транскрипт пропущен")

    call = CommCall(
        source="bitrix", external_id=call_id,
        counterparty_id=cp.id if cp else None,
        contact_id=contact.id if contact else None,
        user_id=manager.id if manager else None,
        direction=_TYPE_MAP.get(str(p.get("CALL_TYPE"))),
        phone=p.get("PHONE_NUMBER"), started_at=p.get("CALL_START_DATE"),
        duration_sec=int(p["CALL_DURATION"]) if p.get("CALL_DURATION") else None,
        recording_path=media, transcript=transcript, transcript_lang=lang,
    )
    s.add(call)
    return call


def main() -> None:
    if not config.BITRIX_WEBHOOK:
        print("[X] BITRIX_WEBHOOK не задан (connectors/.env).")
        sys.exit(1)
    db_url = os.getenv("AIOS_DATABASE_URL", "sqlite:///./dev.db")
    if not db_url.startswith("sqlite"):
        print(f"[X] Прототип рассчитан на SQLite, а AIOS_DATABASE_URL={db_url}")
        sys.exit(1)

    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3
    files = sorted(glob.glob(os.path.join(config.INBOX_DIR, "bitrix_call_*.json")))[:limit]
    if not files:
        print(f"[X] В {config.INBOX_DIR} нет звонков. Сначала: python -m connectors.smoke download {limit}")
        sys.exit(1)

    engine = create_engine(db_url)
    # Создаём только нужные прототипу таблицы (не всю metadata ядра — там есть FK на
    # таблицы модулей, не импортированных здесь, напр. ref_nomenclature_category).
    Base.metadata.create_all(engine, tables=[
        Counterparty.__table__, CounterpartyAlias.__table__,
        Contact.__table__, User.__table__, CommCall.__table__,
    ])
    print(f"БД: {db_url} | обрабатываем {len(files)} звонк(ов)")

    with Session(engine) as s:
        for f in files:
            record = json.load(open(f, encoding="utf-8"))
            process(s, record)
            s.commit()  # прототип: коммитим по звонку (в проде границей владеет воркер)

        cnt = len(s.scalars(select(CommCall)).all())
        with_text = len(s.scalars(select(CommCall).where(CommCall.transcript.isnot(None))).all())
    print(f"\n[OK] В базе comm_call: {cnt} звонк(ов), из них с транскриптом: {with_text}. "
          f"Проверить: клиенты/контакты/менеджеры в counterparty/contact/app_user. "
          f"Время {datetime.now().strftime('%H:%M:%S')}.")


if __name__ == "__main__":
    main()
