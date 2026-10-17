"""Source masks, sealed identity digests and transactional native ID bindings."""
import hashlib
import json
from copy import deepcopy

import pytest
from sqlalchemy import func, select

from core.domain.models import Counterparty, CounterpartyAlias
from core.services.mdm import CounterpartyWriteError
from core.services.native_catalog_import import (
    COUNTERPARTIES,
    CatalogImportConflict,
    SourceRow,
    digest,
)
from core.services.onec_counterparty_import import (
    COUNTRY,
    KIND,
    apply_counterparty_plan,
    build_counterparty_plan,
)

REF = "00000000-0000-0000-0000-000000000100"
LEGAL = "00000000-0000-0000-0000-000000000001"
BY = "00000000-0000-0000-0000-000000000002"
RU = "00000000-0000-0000-0000-000000000003"
ADDRESS = "Synthetic registered address, 1"
SUPPORT = {
    KIND: [{"Ref_Key": LEGAL, "Predefined": True, "DeletionMark": False, "Тип": "Адрес",
            "PredefinedDataName": "ЮрАдресКонтрагента", "ИмяПредопределенногоВида": "ЮрАдресКонтрагента"}],
    COUNTRY: [{"Ref_Key": BY, "DeletionMark": False, "КодАльфа2": "BY", "КодАльфа3": "BLR", "Code": "112"},
              {"Ref_Key": RU, "DeletionMark": False, "КодАльфа2": "RU", "КодАльфа3": "RUS", "Code": "643"}],
}


def _row(**changes):
    return {"Ref_Key": REF, "DataVersion": "version-1", "Description": "Working source name",
            "НаименованиеПолное": "Source legal name", "ИНН": "191000001", "DeletionMark": False,
            "ОбособленноеПодразделение": False, "СтранаРегистрации_Key": BY,
            "КонтактнаяИнформация": [{"Вид_Key": LEGAL, "Тип": "Адрес", "Представление": ADDRESS}], **changes}


def _candidate_digest(rows):
    pairs = sorted((row["Ref_Key"], row["DataVersion"]) for row in rows)
    return hashlib.sha256(json.dumps(pairs, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _plan(rows, *, complete=None, support=None, **options):
    return build_counterparty_plan(
        [SourceRow(COUNTERPARTIES, json.dumps(row, ensure_ascii=True)) for row in rows],
        SUPPORT if support is None else support,
        expected_candidate_digest=_candidate_digest(rows if complete is None else complete),
        expected_legal_kind_digest=hashlib.sha256(LEGAL.encode()).hexdigest(), **options,
    )


def test_source_fields_preserved_and_no_false_legal_confirmation():
    row = _row(Description="  Original name  ")
    before = deepcopy(row)
    plan = _plan([row])
    assert row == before and SUPPORT[COUNTRY][0]["Code"] == "112"
    assert len(plan.ready) == plan.source_complete_count == 1 and not plan.held
    draft = plan.ready[0]
    assert draft.name == "  Original name  " and draft.legal_address == ADDRESS
    assert draft.source_guid == REF and draft.data_version == "version-1"
    assert draft.source_sha == digest(json.dumps(row, ensure_ascii=True))
    assert ADDRESS not in repr(plan) and row["Description"] not in repr(plan)


def test_tab_separators_normalized_only_in_target_legal_name():
    row = _row(НаименованиеПолное="  Source\t\tlegal\tname  ")
    original = deepcopy(row)
    raw = json.dumps(row, ensure_ascii=True)
    plan = _plan([row])
    assert row == original and not plan.held
    draft = plan.ready[0]
    assert draft.legal_name == "  Source  legal name  "
    assert draft.name == row["Description"] and draft.legal_address == ADDRESS
    assert draft.source_guid == REF and draft.data_version == row["DataVersion"]
    assert draft.source_sha == digest(raw)
    assert plan.candidate_digest == _candidate_digest([original])


@pytest.mark.parametrize("legal_name", ["", "\t \t", "Source\tname\n", "Source\tname\x7f", 123,
                                        "x" * 255 + "\t"])
def test_tab_normalization_preserves_other_legal_name_holds(legal_name):
    row = _row(НаименованиеПолное=legal_name)
    plan = _plan([row])
    assert not plan.ready and plan.source_complete_count == 1
    assert plan.held[0].reason == "native_legal_name_invalid"
    assert plan.held[0].source_sha == digest(json.dumps(row, ensure_ascii=True))


@pytest.mark.parametrize("field", ["name", "address"])
def test_tab_in_other_fields_is_still_held(field):
    changes = ({"Description": "Source\tname"} if field == "name" else
               {"КонтактнаяИнформация": [{"Вид_Key": LEGAL, "Тип": "Адрес", "Представление": "Source\taddress"}]})
    plan = _plan([_row(**changes)])
    assert not plan.ready
    assert plan.held[0].reason == ("native_name_invalid" if field == "name" else "native_legal_address_invalid")


def test_optional_legal_name_none_remains_none():
    plan = _plan([_row(НаименованиеПолное=None)])
    assert not plan.held and plan.ready[0].legal_name is None


@pytest.mark.parametrize(("changes", "reason"), [
    ({"DeletionMark": True}, "deleted"),
    ({"ОбособленноеПодразделение": True}, "branch_needs_separate_policy"),
    ({"СтранаРегистрации_Key": None}, "country_missing_or_codes_unproved"),
    ({"СтранаРегистрации_Key": RU}, "foreign_source_codes_need_policy"),
    ({"ИНН": "123"}, "unp_not_nine_ascii_digits"),
    ({"КонтактнаяИнформация": None}, "contact_collection_invalid"),
    ({"КонтактнаяИнформация": []}, "legal_address_missing"),
    ({"КонтактнаяИнформация": [{"Вид_Key": LEGAL, "Тип": "Адрес", "Представление": ADDRESS}] * 2}, "legal_address_ambiguous"),
    ({"КонтактнаяИнформация": [{"Вид_Key": LEGAL, "Тип": "Телефон", "Представление": ADDRESS}]}, "legal_address_wrong_type"),
    ({"КонтактнаяИнформация": [{"Вид_Key": LEGAL, "Тип": "Адрес", "Представление": " "}]}, "legal_address_representation_empty"),
])
def test_original_source_exclusions_retained(changes, reason):
    plan = _plan([_row(**changes)], complete=[])
    assert not plan.ready and plan.source_complete_count == 0
    assert [(hold.source_guid, hold.reason) for hold in plan.held] == [(REF, reason)]


def test_active_duplicate_unp_held_instead_of_arbitrary_match():
    rows = [_row(), _row(Ref_Key="00000000-0000-0000-0000-000000000101")]
    plan = _plan(rows, complete=[])
    assert not plan.ready and len(plan.held) == 2
    assert {hold.reason for hold in plan.held} == {"duplicate_active_by_unp"}


@pytest.mark.parametrize(("mask", "reason"), [
    ("DeletionMark", "deleted"), ("ОбособленноеПодразделение", "branch_needs_separate_policy"),
])
def test_excluded_bad_country_does_not_abort_other_ready_rows(mask, reason):
    ready = _row()
    held = _row(Ref_Key="00000000-0000-0000-0000-000000000101",
                СтранаРегистрации_Key="bad-guid", **{mask: True})
    plan = _plan([ready, held], complete=[ready])
    assert len(plan.ready) == 1 and plan.ready[0].source_guid == REF
    assert len(plan.held) == 1 and plan.held[0].reason == reason


@pytest.mark.parametrize(("changes", "reason"), [
    ({"Description": "n" * 256}, "native_name_invalid"),
    ({"НаименованиеПолное": "n" * 256}, "native_legal_name_invalid"),
    ({"КонтактнаяИнформация": [{"Вид_Key": LEGAL, "Тип": "Адрес", "Представление": "bad\naddress"}]}, "native_legal_address_invalid"),
    ({"КонтактнаяИнформация": [{"Вид_Key": LEGAL, "Тип": "Адрес", "Представление": "bad\ud800address"}]}, "native_legal_address_invalid"),
])
def test_native_text_hold_does_not_change_source_candidate_digest(changes, reason):
    row = _row(**changes)
    plan = _plan([row])
    assert not plan.ready and plan.source_complete_count == 1
    assert plan.candidate_digest == _candidate_digest([row]) and plan.held[0].reason == reason


@pytest.mark.parametrize("key", ["Predefined", "DeletionMark", "Тип", "PredefinedDataName"])
def test_unconfirmed_legal_kind_cannot_supply_an_address(key):
    support = deepcopy(SUPPORT)
    support[KIND][0][key] = "invalid"
    with pytest.raises(CatalogImportConflict, match="COUNTERPARTY_LEGAL_KIND"):
        _plan([_row()], support=support)


def test_changed_legal_kind_guid_is_rejected_even_with_same_name():
    support = deepcopy(SUPPORT)
    support[KIND][0]["Ref_Key"] = "00000000-0000-0000-0000-000000000004"
    with pytest.raises(CatalogImportConflict, match="COUNTERPARTY_LEGAL_KIND_IDENTITY"):
        _plan([_row()], support=support)


def test_changed_version_or_duplicate_identity_rejected_before_admission():
    rows = [SourceRow(COUNTERPARTIES, json.dumps(_row(DataVersion="version-2")))]
    with pytest.raises(CatalogImportConflict, match="COUNTERPARTY_CANDIDATE_DIGEST_CHANGED"):
        build_counterparty_plan(rows, SUPPORT, expected_candidate_digest=_candidate_digest([_row()]),
                                expected_legal_kind_digest=hashlib.sha256(LEGAL.encode()).hexdigest())
    with pytest.raises(CatalogImportConflict, match="COUNTERPARTY_SOURCE_DUPLICATE"):
        _plan([_row(), _row()])


async def test_native_ready_subset_replays_with_private_exact_bindings(session):
    ready, held = _row(), _row(Ref_Key="00000000-0000-0000-0000-000000000101", DeletionMark=True)
    plan = _plan([ready, held], complete=[ready])
    first = await apply_counterparty_plan(session, plan)
    second = await apply_counterparty_plan(session, plan)
    assert first["summary"]["created"] == 1 and second["summary"]["created"] == 0
    assert first["bindings"] == second["bindings"] and first["held"] == second["held"] == 1
    cp = await session.scalar(select(Counterparty))
    assert first["bindings"] == [{"source_guid": REF, "data_version": "version-1",
                                  "source_sha": plan.ready[0].source_sha, "counterparty_id": cp.id}]
    assert cp.requisites["legal_address"] == ADDRESS
    assert await session.scalar(select(func.count()).select_from(CounterpartyAlias)) == 1


async def test_normalized_legal_name_replays_without_duplicate_card_or_alias(session):
    row = _row(НаименованиеПолное="Source\tlegal name")
    plan = _plan([row])
    first = await apply_counterparty_plan(session, plan)
    second = await apply_counterparty_plan(session, plan)
    cp = await session.scalar(select(Counterparty))
    assert cp.legal_name == "Source legal name"
    assert cp.provenance["legal_name"]["source"] == "1c"
    assert first["summary"]["created"] == 1 and second["summary"]["created"] == 0
    assert first["bindings"] == second["bindings"]
    assert first["bindings"][0]["source_sha"] == digest(json.dumps(row, ensure_ascii=True))
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 1
    assert await session.scalar(select(func.count()).select_from(CounterpartyAlias)) == 1


@pytest.mark.parametrize("owner", ["manual", "mns_grp"])
async def test_normalized_import_preserves_protected_legal_name_and_provenance(session, owner):
    provenance = {"legal_name": {"source": owner, "at": "2026-07-01"}}
    cp = Counterparty(name="Working name", legal_name="Protected legal name", unp="191000001",
                      requisites={"legal_address": ADDRESS}, provenance=deepcopy(provenance))
    session.add(cp)
    await session.flush()
    plan = _plan([_row(НаименованиеПолное="Source\tlegal name")])
    result = await apply_counterparty_plan(session, plan)
    assert cp.legal_name == "Protected legal name"
    assert cp.provenance["legal_name"] == provenance["legal_name"]
    assert result["summary"]["created"] == 0
    assert result["bindings"][0]["counterparty_id"] == cp.id
    assert await session.scalar(select(func.count()).select_from(CounterpartyAlias)) == 1


async def test_merged_alias_returns_active_head_without_reassignment(session):
    head = Counterparty(name="Head", unp="191000001", requisites={"legal_address": ADDRESS})
    session.add(head)
    await session.flush()
    duplicate = Counterparty(name="Duplicate", unp="191000001", is_active=False, merged_into_id=head.id)
    session.add(duplicate)
    await session.flush()
    alias = CounterpartyAlias(counterparty_id=duplicate.id, source="1c", external_ref=REF)
    session.add(alias)
    await session.flush()
    result = await apply_counterparty_plan(session, _plan([_row()]))
    assert result["bindings"][0]["counterparty_id"] == head.id and alias.counterparty_id == duplicate.id
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 2


async def test_target_conflict_rolls_back_prior_ready_card_and_alias(session):
    conflict = Counterparty(name="Existing", unp="191000099", requisites={"legal_address": ADDRESS})
    session.add(conflict)
    await session.flush()
    second_guid = "00000000-0000-0000-0000-000000000101"
    session.add(CounterpartyAlias(counterparty_id=conflict.id, source="1c", external_ref=second_guid))
    await session.commit()
    plan = _plan([_row(), _row(Ref_Key=second_guid, ИНН="191000002")])
    with pytest.raises(CounterpartyWriteError, match="Внешний ID"):
        async with session.begin():
            await apply_counterparty_plan(session, plan)
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 1
    assert await session.scalar(select(func.count()).select_from(CounterpartyAlias)) == 1
