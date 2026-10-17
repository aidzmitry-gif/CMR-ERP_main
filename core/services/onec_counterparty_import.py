"""Map sealed caller-provided 1C observations to native cards; no I/O or commit.

Source eligibility is separate from native text validity and target conflicts.
The caller verifies snapshot seals, owns the transaction and keeps returned
GUID/version/native-ID bindings private. Staged catalog holds are not promoted.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from core.domain.models import Counterparty, CounterpartyAlias
from core.services.mdm import CounterpartyWriteError
from core.services.native_catalog_import import (
    COUNTERPARTIES,
    CatalogImportConflict,
    SourceRow,
    digest,
    guid,
)
from core.services.reference_import import import_counterparties

LEGAL_NAME = "ЮрАдресКонтрагента"
KIND = "Catalog_ВидыКонтактнойИнформации"
COUNTRY = "Catalog_СтраныМира"
ZERO = "00000000-0000-0000-0000-000000000000"


@dataclass(frozen=True)
class CounterpartyDraft:
    source_guid: str
    data_version: str
    source_sha: str
    unp: str = field(repr=False)
    name: str = field(repr=False)
    legal_name: str | None = field(repr=False)
    legal_address: str = field(repr=False)


@dataclass(frozen=True)
class CounterpartyHold:
    source_guid: str
    data_version: str
    source_sha: str
    reason: str


@dataclass(frozen=True)
class CounterpartyPlan:
    ready: tuple[CounterpartyDraft, ...]
    held: tuple[CounterpartyHold, ...]
    candidate_digest: str
    source_complete_count: int


def _text_valid(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return not any(ord(char) < 32 or ord(char) == 127 for char in value)


def _support(catalogs):
    if not isinstance(catalogs, dict) or any(not isinstance(catalogs.get(key), list) for key in (KIND, COUNTRY)):
        raise CatalogImportConflict("COUNTERPARTY_SUPPORT_SHAPE")
    if any(not isinstance(row, dict) for key in (KIND, COUNTRY) for row in catalogs[key]):
        raise CatalogImportConflict("COUNTERPARTY_SUPPORT_SHAPE")
    legal = [row for row in catalogs[KIND] if row.get("PredefinedDataName") == LEGAL_NAME
             or row.get("ИмяПредопределенногоВида") == LEGAL_NAME]
    if len(legal) != 1:
        raise CatalogImportConflict("COUNTERPARTY_LEGAL_KIND_CARDINALITY")
    kind = legal[0]
    if (kind.get("Predefined") is not True or kind.get("DeletionMark") is not False
        or kind.get("PredefinedDataName") != LEGAL_NAME or kind.get("ИмяПредопределенногоВида") != LEGAL_NAME
        or kind.get("Тип") != "Адрес"):
        raise CatalogImportConflict("COUNTERPARTY_LEGAL_KIND_SEMANTICS")
    legal_key = guid(kind.get("Ref_Key"))
    countries = {}
    for row in catalogs[COUNTRY]:
        key = guid(row.get("Ref_Key"))
        if key in countries:
            raise CatalogImportConflict("COUNTERPARTY_COUNTRY_DUPLICATE")
        classification = "unknown"
        a2, a3, code = row.get("КодАльфа2"), row.get("КодАльфа3"), row.get("Code")
        if (row.get("DeletionMark") is False and isinstance(a2, str) and isinstance(a3, str)
            and isinstance(code, str) and re.fullmatch(r"[A-Z]{2}", a2)
            and re.fullmatch(r"[A-Z]{3}", a3) and re.fullmatch(r"[0-9]{3}", code)):
            if a2 == "BY" and a3 == "BLR":
                classification = "BY"
            elif a2 != "BY" and a3 != "BLR":
                classification = "foreign_source_codes"
        countries[key] = classification
    if sum(value == "BY" for value in countries.values()) != 1:
        raise CatalogImportConflict("COUNTERPARTY_BY_COUNTRY_CARDINALITY")
    return legal_key, countries


def build_counterparty_plan(rows: list[SourceRow], catalogs: dict, *, expected_candidate_digest: str,
                            expected_legal_kind_digest: str) -> CounterpartyPlan:
    """Retain every observation; compare accepted source identities before native holds."""
    for value in (expected_candidate_digest, expected_legal_kind_digest):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise CatalogImportConflict("COUNTERPARTY_EXPECTED_DIGEST")
    legal_key, countries = _support(catalogs)
    if sha256(legal_key.encode()).hexdigest() != expected_legal_kind_digest:
        raise CatalogImportConflict("COUNTERPARTY_LEGAL_KIND_IDENTITY")
    parsed, seen, base_unps = [], set(), Counter()
    for observation in rows:
        if observation.entity != COUNTERPARTIES:
            raise CatalogImportConflict("COUNTERPARTY_SOURCE_ENTITY")
        key, row = observation.parse()
        if key in seen:
            raise CatalogImportConflict("COUNTERPARTY_SOURCE_DUPLICATE")
        seen.add(key)
        if type(row.get("ОбособленноеПодразделение")) is not bool:
            raise CatalogImportConflict("COUNTERPARTY_SOURCE_BRANCH_TYPE")
        if not _text_valid(row["DataVersion"], 255):
            raise CatalogImportConflict("COUNTERPARTY_SOURCE_DATA_VERSION")
        country = "unknown"
        if not row["DeletionMark"] and not row["ОбособленноеПодразделение"]:
            country_ref = row.get("СтранаРегистрации_Key")
            country = countries.get(guid(country_ref), "unknown") if isinstance(country_ref, str) and country_ref not in ("", ZERO) else "unknown"
        unp = row.get("ИНН")
        reason = ("deleted" if row["DeletionMark"] else
                  "branch_needs_separate_policy" if row["ОбособленноеПодразделение"] else
                  "country_missing_or_codes_unproved" if country == "unknown" else
                  "foreign_source_codes_need_policy" if country != "BY" else
                  "unp_not_nine_ascii_digits" if not isinstance(unp, str) or not re.fullmatch(r"[0-9]{9}", unp) else None)
        if reason is None:
            base_unps[unp] += 1
        parsed.append((observation, key, row, reason))
    ready, held, complete = [], [], []
    for observation, key, row, reason in parsed:
        address = None
        legal_name = row.get("НаименованиеПолное")
        if isinstance(legal_name, str):
            # Normalize a source separator in the target; keep the sealed source unchanged.
            legal_name = legal_name.replace("\t", " ")
        if reason is None:
            contacts = row.get("КонтактнаяИнформация")
            if base_unps[row["ИНН"]] > 1:
                reason = "duplicate_active_by_unp"
            elif not isinstance(contacts, list) or any(not isinstance(line, dict) for line in contacts):
                reason = "contact_collection_invalid"
            else:
                lines = [line for line in contacts if isinstance(line.get("Вид_Key"), str)
                         and line["Вид_Key"] not in ("", ZERO) and guid(line["Вид_Key"]) == legal_key]
                if not lines:
                    reason = "legal_address_missing"
                elif len(lines) != 1:
                    reason = "legal_address_ambiguous"
                elif lines[0].get("Тип") != "Адрес":
                    reason = "legal_address_wrong_type"
                elif not isinstance(lines[0].get("Представление"), str) or not lines[0]["Представление"].strip():
                    reason = "legal_address_representation_empty"
                else:
                    address = lines[0]["Представление"]
                    complete.append((key, row["DataVersion"]))
        if reason is None:
            if not _text_valid(row["Description"], 255):
                reason = "native_name_invalid"
            elif legal_name is not None and not _text_valid(legal_name, 255):
                reason = "native_legal_name_invalid"
            elif not _text_valid(address, 1000):
                reason = "native_legal_address_invalid"
        source_sha = digest(observation.source_text)
        if reason is None:
            ready.append(CounterpartyDraft(key, row["DataVersion"], source_sha, row["ИНН"], row["Description"],
                                           legal_name, address))
        else:
            held.append(CounterpartyHold(key, row["DataVersion"], source_sha, reason))
    candidate_digest = sha256(json.dumps(sorted(complete), ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    if candidate_digest != expected_candidate_digest:
        raise CatalogImportConflict("COUNTERPARTY_CANDIDATE_DIGEST_CHANGED")
    return CounterpartyPlan(tuple(ready), tuple(held), candidate_digest, len(complete))


async def apply_counterparty_plan(session: AsyncSession, plan: CounterpartyPlan) -> dict:
    """Admit READY only; caller must roll back on any conflict. No commit here."""
    summary = await import_counterparties(session, [
        {"id": row.source_guid, "unp": row.unp, "name": row.name,
         "legal_name": row.legal_name, "legal_address": row.legal_address}
        for row in plan.ready
    ])
    linked, target = aliased(Counterparty), aliased(Counterparty)
    bindings = {}
    if plan.ready:
        result = await session.execute(select(CounterpartyAlias.external_ref, target.id, target.unp,
                                              target.is_active, target.merged_into_id)
            .join(linked, linked.id == CounterpartyAlias.counterparty_id)
            .join(target, target.id == func.coalesce(linked.merged_into_id, linked.id))
            .where(CounterpartyAlias.source == "1c",
                   CounterpartyAlias.external_ref.in_([row.source_guid for row in plan.ready])))
        bindings = {ref: (native_id, unp, active, merged) for ref, native_id, unp, active, merged in result}
    if set(bindings) != {row.source_guid for row in plan.ready}:
        raise CounterpartyWriteError("source_binding_missing", "Не удалось подтвердить связи источника")
    for row in plan.ready:
        _, unp, active, merged = bindings[row.source_guid]
        if unp != row.unp or not active or merged is not None:
            raise CounterpartyWriteError("source_identity_conflict", "Связь источника не соответствует действующей карточке")
    return {"summary": summary, "bindings": [
        {"source_guid": row.source_guid, "data_version": row.data_version, "source_sha": row.source_sha,
         "counterparty_id": bindings[row.source_guid][0]} for row in plan.ready
    ], "held": len(plan.held)}
