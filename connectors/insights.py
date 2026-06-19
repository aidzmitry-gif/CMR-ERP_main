"""Извлечение знаний из транскриптов звонков (вариант A) → summary + факты.

Читает уже сохранённые звонки из comm_call (БД заполнил enrich.py), для каждого:
  1. классифицирует звонок: client | inbound_request | spam | unknown;
  2. детерминированно (по правилам, без LLM) вытаскивает факты: товары, объём, имена,
     договорённости, телефоны — то, что надёжно ловится в русском тексте;
  3. опционально обогащает через Claude API, если задан ANTHROPIC_API_KEY (иначе пропускает);
  4. пишет summary в comm_call и факты в comm_insight.

Не зависит от Bitrix (портал не нужен) — работает на локальной dev-БД.

Запуск из корня проекта:
    $env:AIOS_DATABASE_URL = "sqlite:///./dev_calls.db"
    python -m connectors.insights
"""
from __future__ import annotations

import os
import re
import sys

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from .enrich import CommCall, CommInsight

# --- словари для детерминированного разбора (домен: аккумуляторы/электроника) ---

# маркеры спама/холодных предложений (реклама, агентства, «продвижение»)
_SPAM = re.compile(
    r"(агентств|реклам|продвиж|маркетинг|seo|сотруднич|коммерческ\w+ предложен|"
    r"отдел аналитик|собираем стат)", re.I)

# товары/номенклатура домена
_PRODUCTS = [
    (re.compile(r"гелев\w+|чист\w+ гель|\bгель\b|\bгел[ею]\b", re.I), "гелевые аккумуляторы"),
    (re.compile(r"agm|агм", re.I), "AGM-аккумуляторы"),
    (re.compile(r"свинцово-кислот", re.I), "свинцово-кислотные АКБ"),
    (re.compile(r"аккумулятор|акб|батаре", re.I), "аккумуляторы"),
    (re.compile(r"\bgx\s?\d{3,4}\b|sonnenschein|зонненшайн|дельт[аы]", re.I), "модель/бренд АКБ"),
]

# объём/ёмкость
_QTY = re.compile(r"(\d+)\s*(штук|шт\.?|аккумулятор)", re.I)
_CAP = re.compile(r"(\d{2,3})\s*(ампер[\s-]*час|а[/\s]*ч|ач)", re.I)

# договорённости / следующий шаг
_AGREEMENT = re.compile(
    r"(перезвон\w+|жду|договорил\w+|вышлю|отправ\w+ реквизит|готов(?:ы)? (?:к|на)|"
    r"в течение получаса|счёт|счет|реквизит)", re.I)

# срочность / риск (потеря клиента, конкуренты)
_RISK = re.compile(r"(конкурент\w+ .*подвел|зарекся|срочн|как можно быстрее|важн\w+ срок)", re.I)


def _sentences(t: str) -> list[str]:
    return [s.strip() for s in re.split(r"[.!?]\s+", t) if s.strip()]


def classify(t: str) -> str:
    if _SPAM.search(t):
        return "spam"
    if re.search(r"аккумулятор|акб|гель|agm|батаре", t, re.I):
        return "inbound_request"
    return "unknown"


def extract_rule(t: str) -> list[tuple[str, str]]:
    """Детерминированно извлечь факты. Возвращает список (kind, text)."""
    facts: list[tuple[str, str]] = []
    found_products = {label for rx, label in _PRODUCTS if rx.search(t)}
    for label in found_products:
        facts.append(("product", label))

    caps = sorted({m.group(1) for m in _CAP.finditer(t)}, key=int)
    if caps:
        facts.append(("need", f"ёмкость: {', '.join(caps)} А·ч"))
    qtys = sorted({int(m.group(1)) for m in _QTY.finditer(t)})
    if qtys:
        facts.append(("need", f"объём: {max(qtys)} шт (упоминалось {qtys})"))

    # договорённости — берём предложения-носители, не весь текст
    agr = [s for s in _sentences(t) if _AGREEMENT.search(s)][:3]
    for s in agr:
        facts.append(("agreement", s[:200]))

    if _RISK.search(t):
        risk = next((s for s in _sentences(t) if _RISK.search(s)), "")
        facts.append(("risk", risk[:200] or "упомянута срочность/недовольство конкурентами"))
    return facts


def summarize_rule(kind: str, facts: list[tuple[str, str]]) -> str:
    if kind == "spam":
        return "Холодный звонок/реклама — не релевантно (не клиент)."
    products = [t for k, t in facts if k == "product"]
    needs = [t for k, t in facts if k == "need"]
    parts = []
    if products:
        parts.append("интерес: " + ", ".join(products))
    if needs:
        parts.append("; ".join(needs))
    if any(k == "agreement" for k, _ in facts):
        parts.append("есть договорённость о следующем шаге")
    if any(k == "risk" for k, _ in facts):
        parts.append("⚠ срочно / был негатив с конкурентами")
    return ". ".join(parts).capitalize() if parts else "Содержательных фактов не извлечено."


def _ensure_columns(engine) -> None:
    """Dev: добавить недостающие колонки в comm_call (SQLite ALTER, идемпотентно)."""
    wanted = {
        "summary": "TEXT", "call_kind": "VARCHAR(24)", "category": "VARCHAR(24)",
        "value": "VARCHAR(8)", "outcome": "TEXT", "rep_advice": "TEXT",
    }
    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(comm_call)"))}
        for name, sqltype in wanted.items():
            if name not in cols:
                conn.execute(text(f"ALTER TABLE comm_call ADD COLUMN {name} {sqltype}"))


# --- LLM-слой через LM Studio (локально, OpenAI-совместимый API) ---

LMSTUDIO_URL = os.getenv("LMSTUDIO_URL", "http://localhost:1234/v1")
# Пусто = использовать модель, загруженную в LM Studio сейчас (надёжнее, чем угадывать имя).
# Можно зафиксировать через env LMSTUDIO_MODEL, напр. "qwen/qwen3.6-35b-a3b".
LMSTUDIO_MODEL = os.getenv("LMSTUDIO_MODEL", "")

_LLM_PROMPT = """Ты — ассистент отдела продаж компании, торгующей аккумуляторами и электроникой.
Проанализируй транскрипт телефонного звонка и верни СТРОГО JSON (без markdown, без пояснений).

Сначала классифицируй звонок в поле "category" (одно значение):
- "target_client"   — ЦЕЛЕВОЙ КЛИЕНТ: интересуется НАШИМ товаром (аккумуляторы/электроника),
                       хочет купить, спрашивает цену/наличие/счёт, либо уже наш покупатель.
- "service_supplier"— нам ПРЕДЛАГАЮТ УСЛУГИ (реклама, продвижение, сайт, аналитика и т.п.).
- "goods_supplier"  — нам ПРЕДЛАГАЮТ ТОВАР/поставку (потенциальный поставщик).
- "non_target"      — не наш профиль/регион, бесперспективный запрос.
- "spam"            — мусорный обзвон, робот, навязчивая реклама.
- "service"         — ошиблись номером, пустой/технический/неразборчивый звонок.

Затем верни JSON по схеме:
{
  "category": "<одно из значений выше>",
  "value": "high" | "medium" | "low"  (ценность звонка для продаж),
  "summary": "1-2 предложения делового резюме по-русски",
  "outcome": "что менеджер СДЕЛАЛ/обещал по итогу звонка (1 фраза)",
  "client_company": "название фирмы собеседника, если упомянуто, иначе null",
  "client_person": "имя/ФИО собеседника, если упомянуто, иначе null",
  "client_role": "должность/роль собеседника, если ясна, иначе null",
  "products": ["конкретные товары/модели, которые обсуждали"],
  "quantity": "объём/количество если назван, иначе null",
  "agreements": ["договорённости и следующие шаги"],
  "risk": "риск потери клиента / срочность / негатив, если есть, иначе null",
  "rep_advice": "если category=target_client — КОРОТКИЙ совет нашему продавцу, как работать с этим клиентом (на что давить, что подготовить); иначе null"
}
Извлекай факты ТОЛЬКО из текста, не выдумывай. Транскрипт:

"""


def enrich_llm(transcript: str) -> dict | None:
    """Извлечь структуру через LM Studio. None, если сервер недоступен/ответ не разобран."""
    import json

    import requests
    payload = {
        "messages": [{"role": "user", "content": _LLM_PROMPT + transcript}],
        "temperature": 0.1,
        "max_tokens": 600,
    }
    if LMSTUDIO_MODEL:  # иначе LM Studio берёт текущую загруженную модель
        payload["model"] = LMSTUDIO_MODEL
    try:
        resp = requests.post(f"{LMSTUDIO_URL}/chat/completions", json=payload, timeout=300)
        content = resp.json()["choices"][0]["message"]["content"].strip()
    except (requests.RequestException, KeyError, IndexError) as e:
        print(f"  [LLM недоступен: {type(e).__name__}]")
        return None
    # модель иногда оборачивает JSON в ```json ... ``` — выдёргиваем фигурные скобки
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def main() -> None:
    db_url = os.getenv("AIOS_DATABASE_URL", "sqlite:///./dev_calls.db")
    if not db_url.startswith("sqlite"):
        print(f"[X] Прототип на SQLite, а AIOS_DATABASE_URL={db_url}")
        sys.exit(1)
    engine = create_engine(db_url)
    CommInsight.__table__.create(engine, checkfirst=True)
    _ensure_columns(engine)

    use_llm = os.getenv("USE_LLM", "1") not in ("", "0", "false")
    print(f"Извлечение insights. LLM: {'LM Studio ' + LMSTUDIO_MODEL if use_llm else 'выкл (только правила)'}\n")

    with Session(engine) as s:
        calls = s.scalars(select(CommCall).where(CommCall.transcript.isnot(None))).all()
        for call in calls:
            t = call.transcript or ""
            llm = enrich_llm(t) if use_llm else None

            if llm:  # LLM разобрал — берём его структуру
                category = llm.get("category") or ("spam" if classify(t) == "spam" else "non_target")
                call.value = llm.get("value")
                call.outcome = llm.get("outcome")
                call.rep_advice = llm.get("rep_advice")
                summary = llm.get("summary") or summarize_rule(classify(t), extract_rule(t))
                facts = _facts_from_llm(llm)
                src = "llm"
            else:    # фолбэк на правила (LLM недоступен)
                kind = classify(t)
                category = "spam" if kind == "spam" else "target_client" \
                    if kind == "inbound_request" else "non_target"
                facts = extract_rule(t)
                summary = summarize_rule(kind, facts)
                src = "rule"

            call.category = category
            call.call_kind = category  # совместимость: старое поле = новая категория
            call.summary = summary
            for old in s.scalars(select(CommInsight).where(CommInsight.call_id == call.id)).all():
                s.delete(old)  # идемпотентно при повторном прогоне
            for k, txt in facts:
                s.add(CommInsight(call_id=call.id, kind=k, text=txt, source=src))

            tag = "★ЦЕЛЕВОЙ" if category == "target_client" else category
            print(f"— звонок {call.external_id} [{tag}] ценность={call.value or '?'} ({src})")
            print(f"  резюме: {summary}")
            if call.outcome:
                print(f"  итог: {call.outcome}")
            for k, txt in facts:
                print(f"    · {k}: {txt}")
            if call.rep_advice:
                print(f"  💡 продавцу: {call.rep_advice}")
            print()
        s.commit()
    print(f"[OK] Обработано {len(calls)} звонк(ов). category/value/outcome/rep_advice → comm_call.")


def _as_list(v) -> list[str]:
    """Нормализовать поле LLM в список строк: модель может вернуть list ИЛИ одну строку.
    Без этого `for p in "строка"` итерирует по буквам (был баг с product: а·к·к·у...)."""
    if not v:
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [str(v)]


def _facts_from_llm(llm: dict) -> list[tuple[str, str]]:
    """Развернуть JSON от LLM в список (kind, text) для comm_insight."""
    facts: list[tuple[str, str]] = []
    if llm.get("client_company"):
        facts.append(("company", str(llm["client_company"])))
    if llm.get("client_person"):
        person = str(llm["client_person"])
        if llm.get("client_role"):
            person += f" ({llm['client_role']})"
        facts.append(("contact", person))
    for p in _as_list(llm.get("products")):
        facts.append(("product", p))
    if llm.get("quantity"):
        facts.append(("need", f"объём: {llm['quantity']}"))
    for a in _as_list(llm.get("agreements")):
        facts.append(("agreement", a))
    if llm.get("risk"):
        facts.append(("risk", str(llm["risk"])))
    return facts


if __name__ == "__main__":
    main()
