"""Импорт реальных данных за месяц из Bitrix24 и 1С в ERP (для сквозной проверки).

Период задаётся env (по умолчанию ноябрь 2024):
  IMPORT_FROM=2025-12-01T00:00:00 IMPORT_TO=2026-01-01T00:00:00

Двухфазный ETL с файловым кэшем в data/import_<YYYY-MM>/ (повторный прогон безопасен):
  python scripts/import_month.py extract   # Bitrix REST + 1C OData -> jsonl-кэш
  python scripts/import_month.py load-prices # цены SKU из строк реализаций (кэш)
  python scripts/import_month.py verify    # счётчики по таблицам
  python scripts/import_month.py all

Идемпотентность load: контрагент — CounterpartyAlias(source, external_ref) + склейка по УНП;
сделка — Deal.number = "BX-<id>"; звонок — CallLog.call_id; лид — landing_url = "bitrix://lead/<id>";
платёж (реализация 1С) — Payment.entity_ref = "1c:sale:<Ref_Key>"; SKU — по коду 1С;
цены подбора — StockItem из строк реализаций (последняя Цена за месяц, склад «Главный»).

1С — СТРОГО чтение. $filter по датам/строкам в этой базе запрещён (файловая ИБ),
поэтому ноябрь берём «окном»: бинарный поиск левой границы по $skip при $orderby=Date.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from connectors import config as cfg  # noqa: E402  (грузит connectors/.env)

FROM_ISO = os.getenv("IMPORT_FROM", "2024-11-01T00:00:00")
TO_ISO = os.getenv("IMPORT_TO", "2024-12-01T00:00:00")
LABEL = FROM_ISO[:7]  # "2024-11" — метка месяца для кэша и провенанса
OUT_DIR = PROJECT_ROOT / "data" / f"import_{LABEL}"
# Окно 1С по умолчанию = общему окну; переопределяемо (в ka_copy нет данных до 10.2025 —
# ноябрь-2024 лежит в другой базе «КА свернутая», ждёт публикации её OData).
ONEC_FROM = os.getenv("IMPORT_ONEC_FROM", FROM_ISO)
ONEC_TO = os.getenv("IMPORT_ONEC_TO", TO_ISO)
# Переопределение URL базы 1С (например, ka_copy_3 после публикации), не трогая connectors/.env
ONEC_BASE = os.getenv("IMPORT_ONEC_BASE", "") or cfg.ONEC_BASE_URL

# ---------------------------------------------------------------- Bitrix REST

_last_call = 0.0


def bx(method: str, params: dict | None = None) -> dict:
    """Вызов метода Bitrix REST с троттлингом и ретраями на лимиты/5xx."""
    global _last_call
    for attempt in range(6):
        delta = time.monotonic() - _last_call
        if delta < 0.4:
            time.sleep(0.4 - delta)
        _last_call = time.monotonic()
        resp = requests.post(cfg.BITRIX_WEBHOOK.rstrip("/") + "/" + method,
                             json=params or {}, timeout=90)
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        data = resp.json()
        if data.get("error") in ("QUERY_LIMIT_EXCEEDED", "OVERLOAD_LIMIT"):
            time.sleep(2 ** attempt)
            continue
        if "error" in data:
            raise RuntimeError(f"Bitrix {method}: {data['error']} {data.get('error_description')}")
        return data
    raise RuntimeError(f"Bitrix {method}: исчерпаны ретраи")


def bx_list(method: str, params: dict) -> list[dict]:
    """Полный постраничный обход списочного метода."""
    rows: list[dict] = []
    start = 0
    while True:
        data = bx(method, {**params, "start": start})
        rows.extend(data.get("result") or [])
        if data.get("next") is None:
            return rows
        start = data["next"]


# ---------------------------------------------------------------- 1C OData

_onec = requests.Session()


def onec_get(path: str, params: dict | None = None) -> dict:
    if not _onec.auth:
        _onec.auth = (cfg.ONEC_USER, cfg.ONEC_PASSWORD)
        _onec.headers["Accept"] = "application/json"
    url = ONEC_BASE.rstrip("/") + "/" + path
    for attempt in range(4):
        resp = _onec.get(url, params={"$format": "json", **(params or {})}, timeout=180)
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"1C {path}: исчерпаны ретраи")


def onec_date_at(entity: str, skip: int) -> str | None:
    """Date документа на позиции skip при сортировке по Date (для бинарного поиска)."""
    rows = onec_get(entity, {"$orderby": "Date", "$top": 1, "$skip": skip,
                             "$select": "Date"}).get("value", [])
    return rows[0]["Date"] if rows else None


def onec_window(entity: str, date_from: str, date_to: str) -> list[dict]:
    """Все документы entity с date_from <= Date < date_to ($filter недоступен — окно по $skip)."""
    # верхняя граница числа документов — удвоение skip до пустой страницы
    hi = 1
    while onec_date_at(entity, hi) is not None:
        hi *= 2
    # левая граница окна: первый индекс с Date >= date_from
    lo, r = 0, hi
    while lo < r:
        mid = (lo + r) // 2
        d = onec_date_at(entity, mid)
        if d is None or d >= date_from:
            r = mid
        else:
            lo = mid + 1
    # постраничный проход до выхода за date_to (документы целиком, с табличными частями)
    docs: list[dict] = []
    skip = lo
    while True:
        rows = onec_get(entity, {"$orderby": "Date", "$top": 200, "$skip": skip}).get("value", [])
        if not rows:
            break
        for row in rows:
            if row.get("Date", "") >= date_to:
                return docs
            docs.append(row)
        skip += len(rows)
    return docs


def onec_by_key(catalog: str, ref_key: str, select: str) -> dict | None:
    try:
        return onec_get(f"{catalog}(guid'{ref_key}')", {"$select": select})
    except Exception:
        return None


# ---------------------------------------------------------------- extract

def _dump(name: str, rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"extract: {name} — {len(rows)} записей")


def _load_jsonl(name: str) -> list[dict]:
    path = OUT_DIR / f"{name}.jsonl"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _cached(name: str) -> bool:
    path = OUT_DIR / f"{name}.jsonl"
    if path.exists() and path.stat().st_size > 0:
        print(f"extract: {name} — уже в кэше, пропуск")
        return True
    return False


def _chunks(seq: list, n: int = 50):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def extract() -> None:
    nov = {">=DATE_CREATE": FROM_ISO + "+03:00", "<DATE_CREATE": TO_ISO + "+03:00"}

    if not _cached("bx_deals"):
        _dump("bx_deals", bx_list("crm.deal.list", {"filter": nov, "order": {"ID": "ASC"}, "select": [
            "ID", "TITLE", "STAGE_ID", "CATEGORY_ID", "OPPORTUNITY", "CURRENCY_ID", "COMPANY_ID",
            "CONTACT_ID", "ASSIGNED_BY_ID", "DATE_CREATE", "CLOSEDATE", "SOURCE_ID"]}))
    if not _cached("bx_leads"):
        _dump("bx_leads", bx_list("crm.lead.list", {"filter": nov, "order": {"ID": "ASC"}, "select": [
            "ID", "TITLE", "NAME", "LAST_NAME", "COMPANY_TITLE", "STATUS_ID", "SOURCE_ID",
            "ASSIGNED_BY_ID", "DATE_CREATE", "PHONE", "EMAIL"]}))
    if not _cached("bx_calls"):
        _dump("bx_calls", bx_list("voximplant.statistic.get", {"FILTER": {
            ">=CALL_START_DATE": FROM_ISO + "+03:00", "<CALL_START_DATE": TO_ISO + "+03:00"},
            "SORT": "ID", "ORDER": "ASC"}))
    if not _cached("bx_users"):
        _dump("bx_users", bx_list("user.get", {}))
    if not _cached("bx_sources"):
        _dump("bx_sources", bx("crm.status.list",
                               {"filter": {"ENTITY_ID": "SOURCE"}}).get("result", []))

    deals = _load_jsonl("bx_deals")
    calls = _load_jsonl("bx_calls")
    company_ids = sorted({d["COMPANY_ID"] for d in deals if d.get("COMPANY_ID") not in (None, "0")},
                         key=int)
    contact_ids = {d["CONTACT_ID"] for d in deals if d.get("CONTACT_ID") not in (None, "0")}
    contact_ids |= {c["CRM_ENTITY_ID"] for c in calls
                    if c.get("CRM_ENTITY_TYPE") == "CONTACT" and c.get("CRM_ENTITY_ID")}
    company_ids_from_calls = {c["CRM_ENTITY_ID"] for c in calls
                              if c.get("CRM_ENTITY_TYPE") == "COMPANY" and c.get("CRM_ENTITY_ID")}
    company_ids = sorted(set(company_ids) | {str(x) for x in company_ids_from_calls}, key=int)
    contact_ids = sorted({str(x) for x in contact_ids}, key=int)

    if not _cached("bx_companies"):
        rows = []
        for chunk in _chunks(company_ids):
            rows += bx_list("crm.company.list", {"filter": {"@ID": chunk}, "select": [
                "ID", "TITLE", "PHONE", "EMAIL"]})
        _dump("bx_companies", rows)
    if not _cached("bx_contacts"):
        rows = []
        for chunk in _chunks(contact_ids):
            rows += bx_list("crm.contact.list", {"filter": {"@ID": chunk}, "select": [
                "ID", "NAME", "LAST_NAME", "COMPANY_ID", "PHONE", "EMAIL"]})
        _dump("bx_contacts", rows)
    if not _cached("bx_requisites"):
        rows = []
        for chunk in _chunks(company_ids):
            rows += bx_list("crm.requisite.list", {"filter": {
                "ENTITY_TYPE_ID": "4", "@ENTITY_ID": chunk}, "select": ["ENTITY_ID", "RQ_INN"]})
        _dump("bx_requisites", rows)

    # --- 1С: реализации ноября + ссылочные контрагенты и номенклатура ---
    if not _cached("onec_sales"):
        docs = onec_window("Document_РеализацияТоваровУслуг", ONEC_FROM, ONEC_TO)
        _dump("onec_sales", docs)
    docs = _load_jsonl("onec_sales")
    if docs and not _cached("onec_counterparties"):
        refs = sorted({d["Контрагент_Key"] for d in docs if d.get("Контрагент_Key")})
        rows = [r for r in (onec_by_key("Catalog_Контрагенты", k,
                                        "Ref_Key,Description,НаименованиеПолное,ИНН")
                            for k in refs) if r]
        _dump("onec_counterparties", rows)
    if docs and not _cached("onec_sku"):
        refs = sorted({item["Номенклатура_Key"]
                       for d in docs for item in (d.get("Товары") or [])
                       if item.get("Номенклатура_Key")})
        rows = [r for r in (onec_by_key("Catalog_Номенклатура", k, "Ref_Key,Code,Description")
                            for k in refs) if r]
        _dump("onec_sku", rows)
    print("extract: готово ->", OUT_DIR)


# ---------------------------------------------------------------- load

# Bitrix STAGE_ID (основная воронка, категория 0) -> канон stages.py
STAGE_MAP = {
    "1": "new", "2": "price_req", "UC_J58BGN": "has_price", "NEW": "invoice",
    "UC_OV09QE": "protected", "PREPARATION": "contract", "UC_U2ETYR": "contract",
    "UC_9TE3J7": "contract", "PREPAYMENT_INVOICE": "contract", "UC_RZP5B6": "contract",
    "8": "contract", "9": "contract", "UC_5G5XU7": "contract", "EXECUTING": "contract",
    "UC_LMKLAN": "contract", "FINAL_INVOICE": "contract",
    "WON": "won", "LOSE": "lost",
    "APOLOGY": "lost", "3": "lost", "4": "lost", "5": "lost", "6": "lost", "7": "lost",
}
LOST_TITLES = {
    "APOLOGY": "Купил дешевле", "3": "Купил другое", "4": "Не смогли сделать предложение",
    "5": "Нужен срочно. Нет на складе", "6": "Возврат денег: не привезли вовремя",
    "7": "Другой вариант",
}
LEAD_STATUS_MAP = {"NEW": "new", "5": "qualified", "IN_PROCESS": "qualified",
                   "CONVERTED": "converted"}
LEAD_SOURCE_MAP = {"CALL": "phone", "EMAIL": "email", "WEB": "site", "WEBFORM": "site",
                   "RC_GENERATOR": "site", "STORE": "site", "ONLINE_STORE": "site"}


def _naive(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).replace(tzinfo=None)
    except ValueError:
        return None


def _first_value(multifield) -> str | None:
    if isinstance(multifield, list) and multifield:
        return (multifield[0].get("VALUE") or "").strip() or None
    return None


def _dec(raw, default="0") -> Decimal:
    try:
        return Decimal(str(raw or default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _map_deal_stage(stage_id: str, category: str) -> tuple[str, str, str | None]:
    """-> (stage, funnel, lost_comment). Категория 7 Bitrix — воронка постоянных клиентов."""
    stage_id = stage_id.split(":", 1)[-1]  # Bitrix может отдавать с префиксом категории "C7:WON"
    if category == "7":
        if "WON" in stage_id:
            return "rp_won", "repeat_clients", None
        if stage_id == "LOSE" or stage_id in LOST_TITLES:
            return "rp_lost", "repeat_clients", LOST_TITLES.get(stage_id)
        if "INVOICE" in stage_id or stage_id in ("NEW", "PREPARATION", "EXECUTING"):
            return "rp_invoice", "repeat_clients", None
        return "rp_request", "repeat_clients", None
    stage = STAGE_MAP.get(stage_id, "new")
    return stage, "new_clients", LOST_TITLES.get(stage_id)


async def _load_sales_prices(session, stats: dict) -> None:
    """Цены подбора из строк реализаций 1С (последняя Цена за месяц на SKU)."""
    from datetime import timezone

    from modules.integrations.models import StockItem

    sku_by_ref = {
        row["Ref_Key"]: (row.get("Code") or "").strip()
        for row in _load_jsonl("onec_sku")
        if row.get("Ref_Key") and (row.get("Code") or "").strip()
    }
    if not sku_by_ref:
        return

    latest: dict[str, tuple[datetime | None, Decimal]] = {}
    for doc in _load_jsonl("onec_sales"):
        if doc.get("Posted") is False:
            continue
        doc_date = _naive(doc.get("Date"))
        for line in doc.get("Товары") or []:
            code = sku_by_ref.get(line.get("Номенклатура_Key") or "")
            if not code:
                continue
            price = _dec(line.get("ЦенаСоСкидкой") or line.get("Цена"))
            if price <= 0:
                continue
            prev = latest.get(code)
            if prev is None or (
                doc_date is not None and (prev[0] is None or doc_date >= prev[0])
            ):
                latest[code] = (doc_date, price)

    if not latest:
        return

    warehouse = "Главный"
    existing = {
        (si.sku_code, si.warehouse): si
        for si in (await session.execute(select(StockItem))).scalars()
    }
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for code, (_, price) in latest.items():
        item = existing.get((code, warehouse))
        if item is None:
            item = StockItem(sku_code=code, warehouse=warehouse)
            session.add(item)
            existing[(code, warehouse)] = item
            stats["stock_price"] += 1
        else:
            stats["stock_price_updated"] += 1
        item.price = price
        item.updated_at = now


async def load() -> None:
    from core.domain.models import Contact, Counterparty, CounterpartyAlias, Sku
    from core.services import build_services
    from modules.finance.models import Payment
    from modules.leads.models import Lead
    from modules.sales.models import CallLog, Deal

    services = build_services()
    services.db.init_engine()
    if services.db.is_sqlite:
        await services.db.connect()  # dev-режим: создаст таблицы
    assert services.db.session_factory is not None

    users = {u["ID"]: f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
             for u in _load_jsonl("bx_users")}
    companies = {c["ID"]: c for c in _load_jsonl("bx_companies")}
    contacts_bx = {c["ID"]: c for c in _load_jsonl("bx_contacts")}
    unp_by_company: dict[str, str] = {}
    for r in _load_jsonl("bx_requisites"):
        inn = (r.get("RQ_INN") or "").strip()
        if inn and r["ENTITY_ID"] not in unp_by_company:
            unp_by_company[str(r["ENTITY_ID"])] = inn

    async with services.db.session_factory() as s:
        # --- контрагенты: эталон по УНП, привязка внешних id через alias ---
        aliases = {(a.source, a.external_ref): a.counterparty_id
                   for a in (await s.execute(select(CounterpartyAlias))).scalars()}
        cps = (await s.execute(select(Counterparty))).scalars().all()
        by_unp = {c.unp: c for c in cps if c.unp}
        by_name = {c.name: c for c in cps}
        stats = {k: 0 for k in ("counterparty", "contact", "deal", "lead", "call",
                                "payment", "sku", "stock_price", "stock_price_updated",
                                "date_fallback")}

        def _dt_or_nov1(iso: str | None) -> datetime:
            """Дата или 1 ноября с явным счётчиком фолбэков (не искажать данные молча)."""
            dt = _naive(iso)
            if dt is None:
                stats["date_fallback"] += 1
                return datetime.fromisoformat(FROM_ISO)
            return dt

        async def upsert_cp(source: str, ext: str, name: str, unp: str | None) -> Counterparty:
            key = (source, ext)
            if key in aliases:
                return await s.get(Counterparty, aliases[key])
            cp = (by_unp.get(unp) if unp else None) or by_name.get(name)
            if cp is None:
                prov = {"name": {"source": source, "at": LABEL}}
                if unp:
                    prov["unp"] = {"source": source, "at": LABEL}
                cp = Counterparty(name=name, unp=unp, provenance=prov)
                s.add(cp)
                await s.flush()
                by_name[name] = cp
                if unp:
                    by_unp[unp] = cp
                stats["counterparty"] += 1
            elif unp and not cp.unp:
                cp.unp = unp
                by_unp[unp] = cp
            s.add(CounterpartyAlias(counterparty_id=cp.id, source=source, external_ref=ext))
            aliases[key] = cp.id
            return cp

        cp_by_bx_company: dict[str, Counterparty] = {}
        for cid, comp in companies.items():
            name = (comp.get("TITLE") or f"Компания {cid}").strip()[:255]
            cp_by_bx_company[cid] = await upsert_cp(
                "bitrix", f"company:{cid}", name, unp_by_company.get(cid))

        onec_cp_names: dict[str, str] = {}
        for row in _load_jsonl("onec_counterparties"):
            name = (row.get("Description") or "").strip()[:255] or "Без имени"
            unp = (row.get("ИНН") or "").strip() or None
            await upsert_cp("1c", row["Ref_Key"], name, unp)
            onec_cp_names[row["Ref_Key"]] = name

        # --- контакты Bitrix ---
        existing_contacts = {(c.full_name, c.phone, c.email): c.id
                             for c in (await s.execute(select(Contact))).scalars()}
        contact_id_map: dict[str, int] = {}
        cp_by_bx_contact: dict[str, int] = {}
        for cid, c in contacts_bx.items():
            full_name = f"{c.get('NAME') or ''} {c.get('LAST_NAME') or ''}".strip()[:255]
            full_name = full_name or f"Контакт {cid}"
            phone = (_first_value(c.get("PHONE")) or "")[:64] or None
            email = _first_value(c.get("EMAIL")) or None
            comp = cp_by_bx_company.get(str(c.get("COMPANY_ID") or ""))
            key = (full_name, phone, email)
            if key not in existing_contacts:
                row = Contact(counterparty_id=comp.id if comp else None, full_name=full_name,
                              phone=phone, email=email)
                s.add(row)
                await s.flush()
                existing_contacts[key] = row.id
                stats["contact"] += 1
            contact_id_map[cid] = existing_contacts[key]
            if comp:
                cp_by_bx_contact[cid] = comp.id

        # --- сделки Bitrix (категории 0 — новые клиенты, 7 — постоянные) ---
        existing_deals = set((await s.execute(select(Deal.number))).scalars())
        skipped_categories: dict[str, int] = {}
        for d in _load_jsonl("bx_deals"):
            cat = str(d.get("CATEGORY_ID") or "0")
            if cat not in ("0", "7"):
                skipped_categories[cat] = skipped_categories.get(cat, 0) + 1
                continue
            number = f"BX-{d['ID']}"
            if number in existing_deals:
                continue
            stage, funnel, lost_comment = _map_deal_stage(str(d.get("STAGE_ID") or ""), cat)
            comp = cp_by_bx_company.get(str(d.get("COMPANY_ID") or ""))
            contact = contacts_bx.get(str(d.get("CONTACT_ID") or ""))
            cp_name = comp.name if comp else (
                f"{contact.get('NAME') or ''} {contact.get('LAST_NAME') or ''}".strip()
                if contact else "Не указан")
            created = _dt_or_nov1(d.get("DATE_CREATE"))
            closed = _naive(d.get("CLOSEDATE"))
            terminal = stage in ("won", "lost", "rp_won", "rp_lost")
            s.add(Deal(
                number=number, title=(d.get("TITLE") or number)[:255],
                counterparty=cp_name[:255] or "Не указан",
                amount=_dec(d.get("OPPORTUNITY")), stage=stage, funnel=funnel,
                owner=users.get(str(d.get("ASSIGNED_BY_ID") or ""), "")[:128],
                deal_date=str(created.date()),
                closed_date=str(closed.date()) if (terminal and closed) else None,
                created_at=created, stage_changed_at=(closed if terminal and closed else created),
                lost_comment=lost_comment,
            ))
            existing_deals.add(number)
            stats["deal"] += 1

        # --- лиды Bitrix ---
        existing_leads = set((await s.execute(select(Lead.landing_url))).scalars())
        for ld in _load_jsonl("bx_leads"):
            ext = f"bitrix://lead/{ld['ID']}"
            if ext in existing_leads:
                continue
            status_id = str(ld.get("STATUS_ID") or "NEW")
            name = f"{ld.get('NAME') or ''} {ld.get('LAST_NAME') or ''}".strip()
            s.add(Lead(
                source=LEAD_SOURCE_MAP.get(str(ld.get("SOURCE_ID") or ""), "site"),
                name=(name or (ld.get("TITLE") or ""))[:255],
                company=(ld.get("COMPANY_TITLE") or "")[:255],
                phone=(_first_value(ld.get("PHONE")) or "")[:64] or None,
                email=(_first_value(ld.get("EMAIL")) or "")[:128] or None,
                product=(ld.get("TITLE") or "")[:128],
                status=LEAD_STATUS_MAP.get(status_id, "rejected"),
                assigned_to=users.get(str(ld.get("ASSIGNED_BY_ID") or ""), "")[:128],
                landing_url=ext,
                created_at=_dt_or_nov1(ld.get("DATE_CREATE")),
            ))
            existing_leads.add(ext)
            stats["lead"] += 1

        # --- звонки Bitrix ---
        existing_calls = set((await s.execute(select(CallLog.call_id))).scalars())
        for c in _load_jsonl("bx_calls"):
            call_id = str(c.get("CALL_ID") or c["ID"])[:64]
            if call_id in existing_calls:
                continue
            started = _dt_or_nov1(c.get("CALL_START_DATE"))
            duration = int(c.get("CALL_DURATION") or 0)
            answered = str(c.get("CALL_FAILED_CODE") or "") == "200" and duration > 0
            ent_type, ent_id = c.get("CRM_ENTITY_TYPE"), str(c.get("CRM_ENTITY_ID") or "")
            s.add(CallLog(
                call_id=call_id,
                direction="out" if str(c.get("CALL_TYPE")) in ("1", "4") else "in",
                phone_e164=(c.get("PHONE_NUMBER") or "")[:32] or None,
                owner=users.get(str(c.get("PORTAL_USER_ID") or ""), "")[:128],
                counterparty_id=(cp_by_bx_company[ent_id].id
                                 if ent_type == "COMPANY" and ent_id in cp_by_bx_company
                                 else cp_by_bx_contact.get(ent_id)
                                 if ent_type == "CONTACT" else None),
                contact_id=contact_id_map.get(ent_id) if ent_type == "CONTACT" else None,
                status="ended" if answered else "missed",
                recording_url=(c.get("CALL_RECORD_URL") or "")[:255] or None,
                started_at=started,
                answered_at=started if answered else None,
                ended_at=started + timedelta(seconds=duration),
                duration_sec=duration or None,
            ))
            existing_calls.add(call_id)
            stats["call"] += 1

        # --- реализации 1С -> finance.payment (выручка по факту отгрузки) ---
        existing_refs = set((await s.execute(select(Payment.entity_ref))).scalars())
        for doc in _load_jsonl("onec_sales"):
            if doc.get("Posted") is False:
                continue
            ent = f"1c:sale:{doc['Ref_Key']}"
            if ent in existing_refs:
                continue
            cp_name = onec_cp_names.get(doc.get("Контрагент_Key") or "", "")
            number = (doc.get("Number") or "").strip()
            doc_date = _naive(doc.get("Date"))
            s.add(Payment(
                ref=number or ent, amount=_dec(doc.get("СуммаДокумента")),
                status="paid", kind="receivable",
                paid_at=doc_date, due_date=doc_date.date() if doc_date else None,
                counterparty_ref=cp_name[:64] or None, entity_ref=ent,
                description=f"Реализация {number} от {str(doc.get('Date') or '')[:10]}"[:255],
            ))
            existing_refs.add(ent)
            stats["payment"] += 1

        # --- номенклатура 1С -> SKU (golden record по коду) ---
        existing_sku = set((await s.execute(select(Sku.code))).scalars())
        for row in _load_jsonl("onec_sku"):
            code = (row.get("Code") or "").strip()
            if not code or code in existing_sku:
                continue
            s.add(Sku(code=code, title=(row.get("Description") or code)[:255],
                      provenance={"title": {"source": "1c", "at": LABEL}}))
            existing_sku.add(code)
            stats["sku"] += 1

        await _load_sales_prices(s, stats)

        await s.commit()

    await services.db.disconnect()
    if skipped_categories:
        print("load: пропущены сделки не-продажных воронок Bitrix:", skipped_categories)
    print("load: добавлено —", ", ".join(f"{k}: {v}" for k, v in stats.items()))


async def load_prices() -> None:
    """Только цены подбора из кэша реализаций (без Bitrix/лидов)."""
    from core.services import build_services

    services = build_services()
    services.db.init_engine()
    if services.db.is_sqlite:
        await services.db.connect()
    assert services.db.session_factory is not None
    async with services.db.session_factory() as s:
        stats = {"stock_price": 0, "stock_price_updated": 0}
        await _load_sales_prices(s, stats)
        await s.commit()
    await services.db.disconnect()
    print("load-prices:", ", ".join(f"{k}: {v}" for k, v in stats.items()))


async def verify() -> None:
    from sqlalchemy import func as sa_func

    from core.domain.models import Contact, Counterparty, Sku
    from core.services import build_services
    from modules.finance.models import Payment
    from modules.leads.models import Lead
    from modules.sales.models import CallLog, Deal

    services = build_services()
    services.db.init_engine()
    if services.db.is_sqlite:
        await services.db.connect()
    async with services.db.session_factory() as s:
        for label, model in (("контрагенты", Counterparty), ("контакты", Contact),
                             ("SKU", Sku), ("сделки", Deal), ("лиды", Lead),
                             ("звонки", CallLog), ("платежи", Payment)):
            n = (await s.execute(select(sa_func.count()).select_from(model))).scalar()
            print(f"verify: {label} — {n}")
        total = (await s.execute(
            select(sa_func.coalesce(sa_func.sum(Payment.amount), 0))
            .where(Payment.kind == "receivable"))).scalar()
        print(f"verify: выручка (receivable, BYN) — {total}")
    await services.db.disconnect()


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    os.chdir(PROJECT_ROOT)
    if phase in ("extract", "all"):
        extract()
    if phase in ("load", "all"):
        asyncio.run(load())
    if phase == "load-prices":
        asyncio.run(load_prices())
    if phase in ("verify", "all"):
        asyncio.run(verify())
