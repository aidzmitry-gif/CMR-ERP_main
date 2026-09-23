import base64
import csv
import io
import json

import pytest

from modules.accounting import reconciliation
from modules.accounting.reconciliation import HEADERS, compare, parse_snapshot


def snapshot(*, amount="1.01", org="1", dimensions=None, duplicate=False, blank=False, omit=False,
             status="preliminary", pending="2"):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(HEADERS)
    metadata = [org, "2026-09-01", "2026-09-30", status, pending]
    writer.writerow(["report", *metadata, *([""] * 17)])
    if not omit:
        row = ["balance", *metadata, "001", 'Title; "quoted"', json.dumps(dimensions or {"sku": "A"}), "USD", "Да", "0.00", amount, "0.00", amount, "0", "0", "0", "0", "0", "0.000001", "0", "0.000001"]
        if blank:
            row[11] = ""
        writer.writerow(row)
        if duplicate:
            writer.writerow(row)
    return stream.getvalue().encode("utf-8-sig")


def test_exact_differences_keep_source_hashes_and_do_not_accept_cutover():
    result = compare(snapshot(amount="9007199254740993.01"), snapshot(amount="9007199254740993.02"))
    row, = result["differences"]
    assert row["account"] == "001" and row["off_balance"]
    assert row["fields"]["debit"]["right_minus_left"] == "0.01"
    assert set(row["fields"]) == {"debit", "closing"}
    assert result["left"]["sha256"] != result["right"]["sha256"]
    assert not result["cutover_ready"] and not result["accepted_by_accountant"]


def test_analytical_changes_are_missing_rows_not_net_zero():
    result = compare(snapshot(dimensions={"sku": "A"}), snapshot(dimensions={"sku": "B"}))
    assert {row["presence"] for row in result["differences"]} == {"left_only", "right_only"}
    assert all(row["fields"]["debit"]["right_minus_left"] is None for row in result["differences"])


def test_empty_and_equal_comparisons_retain_preliminary_status():
    for raw in [snapshot(), snapshot(omit=True)]:
        result = compare(raw, raw)
        assert result["status"] == "no_numeric_differences"
        assert result["left"]["pending_documents"] == 2
        assert result["left"]["status"] == "preliminary"
        assert not result["cutover_ready"]


def test_equal_closed_complete_comparison_is_cutover_candidate_but_not_accepted():
    result = compare(snapshot(status="closed_periods", pending="0"),
                     snapshot(status="closed_periods", pending="0"))
    assert result["cutover_ready"] is True
    assert result["eligibility_blockers"] == []
    assert result["accepted_by_accountant"] is False


@pytest.mark.parametrize("other", [snapshot(org="2"), snapshot(duplicate=True), snapshot(blank=True), snapshot(amount="NaN"), snapshot(amount="-1"), snapshot(amount="1.001")])
def test_ambiguous_or_incomplete_inputs_are_rejected(other):
    with pytest.raises(ValueError):
        compare(snapshot(), other)


def test_bad_closing_and_duplicate_json_keys_rejected():
    raw = snapshot().decode("utf-8-sig")
    with pytest.raises(ValueError, match="arithmetic"):
        compare(snapshot(), raw.replace("0.000001", "0.000002", 1).encode())
    raw = raw.replace('{""sku"": ""A""}', '{""sku"": ""A"", ""sku"": ""B""}')
    with pytest.raises(ValueError, match="Duplicate analytical"):
        compare(snapshot(), raw.encode())


async def test_scoped_api_preserves_bytes_and_does_not_post(client, db, book):
    from sqlalchemy import func, select

    from modules.accounting.models import Entry

    raw = snapshot(org=str(book[0]))
    data = {"left_base64": base64.b64encode(raw).decode(), "right_base64": base64.b64encode(raw).decode()}
    path = f"/accounting/organizations/{book[0]}/reconciliation"
    count = await db.scalar(select(func.count()).select_from(Entry))
    response = await client.post(path, json=data)
    assert response.status_code == 200, response.text
    assert response.json()["erp_ledger_verified"] is False
    assert response.json()["eligibility_blockers"] == [
        "reports_not_closed", "pending_documents", "erp_snapshot_mismatch"]
    assert await db.scalar(select(func.count()).select_from(Entry)) == count
    assert (await client.post("/accounting/organizations/999/reconciliation", json=data)).status_code == 403
    foreign = base64.b64encode(snapshot(org="999")).decode()
    assert (await client.post(path, json={"left_base64": foreign, "right_base64": foreign})).status_code == 422
    assert (await client.post(path, json={**data, "left_base64": "!bad!"})).status_code == 422


async def test_erp_export_matches_current_ledger_but_open_period_cannot_be_accepted(client, db, book, posting):
    from modules.accounting import service

    path = f"/accounting/organizations/{book[0]}/reconciliation/erp-osv.csv"
    export = await client.get(f"{path}?start=2026-09-01&end=2026-09-30")
    assert export.status_code == 200, export.text
    assert export.headers["cache-control"] == "private, no-store"
    parsed = parse_snapshot(export.content)
    assert parsed["organization_id"] == str(book[0])
    assert parsed["status"] == "preliminary"
    encoded = base64.b64encode(export.content).decode()
    preview = await client.post(
        f"/accounting/organizations/{book[0]}/reconciliation",
        json={"left_base64": encoded, "right_base64": encoded},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["erp_ledger_verified"] is True
    assert preview.json()["cutover_ready"] is False
    assert preview.json()["eligibility_blockers"] == ["reports_not_closed"]
    assert (await client.get("/accounting/organizations/999/reconciliation/erp-osv.csv?start=2026-09-01&end=2026-09-30")).status_code == 403
    await service.post(db, book[0], posting("after-export"), "tester")
    await db.commit()
    stale = await client.post(
        f"/accounting/organizations/{book[0]}/reconciliation",
        json={"left_base64": encoded, "right_base64": encoded},
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["erp_ledger_verified"] is False
    assert "erp_snapshot_mismatch" in stale.json()["eligibility_blockers"]


async def test_nonmatching_osv_can_be_saved_as_an_immutable_scoped_work_queue(client, db, book):
    from sqlalchemy import func, select

    from modules.accounting.models import Entry, ReconciliationIssue, ReconciliationIssueItem

    left = snapshot(org=str(book[0]), amount="9007199254740993.01", status="closed_periods", pending="0")
    right = snapshot(org=str(book[0]), amount="9007199254740993.02", status="closed_periods", pending="0")
    payload = {
        "request_key": "00000000-0000-4000-8000-000000000021",
        "left_base64": base64.b64encode(left).decode(),
        "right_base64": base64.b64encode(right).decode(),
        "responsible": "accountant:inventory-team",
        "evidence": "Расхождение передано ответственному за складскую аналитику",
    }
    entries_before = await db.scalar(select(func.count()).select_from(Entry))
    response = await client.post(f"/accounting/organizations/{book[0]}/reconciliation/issues", json=payload)
    assert response.status_code == 200, response.text
    issue = response.json()
    assert issue["already_queued"] is False
    assert issue["difference_count"] == 1
    assert issue["eligibility_blockers"] == ["numeric_differences", "erp_snapshot_mismatch"]
    assert issue["responsible"] == payload["responsible"]
    assert issue["requires_fresh_comparison"] is True
    assert issue["accepted_by_accountant"] is False and issue["cutover_ready"] is False
    assert await db.scalar(select(func.count()).select_from(Entry)) == entries_before
    assert await db.scalar(select(func.count()).select_from(ReconciliationIssue)) == 1
    assert await db.scalar(select(func.count()).select_from(ReconciliationIssueItem)) == 1

    listed = await client.get(f"/accounting/organizations/{book[0]}/reconciliation/issues")
    assert listed.status_code == 200
    assert listed.json()["rows"][0]["issue_id"] == issue["issue_id"]
    detail = await client.get(f"/accounting/organizations/{book[0]}/reconciliation/issues/{issue['issue_id']}")
    assert detail.status_code == 200
    row, = detail.json()["items"]
    assert (row["account"], row["presence"], row["fields"]["debit"]["right_minus_left"]) == ("001", "both", "0.01")

    replay = await client.post(f"/accounting/organizations/{book[0]}/reconciliation/issues", json=payload)
    assert replay.status_code == 200
    assert replay.json()["already_queued"] is True
    assert await db.scalar(select(func.count()).select_from(ReconciliationIssue)) == 1
    assert await db.scalar(select(func.count()).select_from(ReconciliationIssueItem)) == 1
    changed = {**payload, "responsible": "accountant:another-team"}
    assert (await client.post(f"/accounting/organizations/{book[0]}/reconciliation/issues", json=changed)).status_code == 422


async def test_queue_keeps_non_numeric_blockers_but_never_accepts_or_queues_an_eligible_pair(client, db, book, monkeypatch):
    from sqlalchemy import func, select

    from modules.accounting.models import ReconciliationIssue, ReconciliationReceipt

    raw = snapshot(org=str(book[0]), status="preliminary", pending="2")
    payload = {
        "request_key": "00000000-0000-4000-8000-000000000022",
        "left_base64": base64.b64encode(raw).decode(),
        "right_base64": base64.b64encode(raw).decode(),
        "responsible": "accountant:period-close",
        "evidence": "До закрытия периода назначен контроль непроведённых документов",
    }
    response = await client.post(f"/accounting/organizations/{book[0]}/reconciliation/issues", json=payload)
    assert response.status_code == 200, response.text
    issue = response.json()
    assert issue["difference_count"] == 0
    assert issue["eligibility_blockers"] == [
        "reports_not_closed", "pending_documents", "erp_snapshot_mismatch"]
    detail = await client.get(f"/accounting/organizations/{book[0]}/reconciliation/issues/{issue['issue_id']}")
    assert detail.json()["items"] == []
    assert await db.scalar(select(func.count()).select_from(ReconciliationReceipt)) == 0

    closed = snapshot(org=str(book[0]), status="closed_periods", pending="0")
    async def matching_ledger(_session, _org_id, _start, _end):
        return closed
    monkeypatch.setattr(reconciliation, "erp_snapshot", matching_ledger)
    ready = {**payload, "request_key": "00000000-0000-4000-8000-000000000023",
             "left_base64": base64.b64encode(closed).decode(), "right_base64": base64.b64encode(closed).decode()}
    rejected = await client.post(f"/accounting/organizations/{book[0]}/reconciliation/issues", json=ready)
    assert rejected.status_code == 422 and "подтвердите протокол" in rejected.text
    assert await db.scalar(select(func.count()).select_from(ReconciliationIssue)) == 1


async def test_accountant_can_accept_only_closed_equal_pair_and_replay_is_idempotent(client, db, book, monkeypatch):
    from sqlalchemy import func, select

    from modules.accounting.models import Entry, ReconciliationReceipt

    raw = snapshot(org=str(book[0]), status="closed_periods", pending="0")
    async def matching_ledger(_session, _org_id, _start, _end):
        return raw
    monkeypatch.setattr(reconciliation, "erp_snapshot", matching_ledger)
    data = {
        "request_key": "00000000-0000-4000-8000-000000000001",
        "left_base64": base64.b64encode(raw).decode(),
        "right_base64": base64.b64encode(raw).decode(),
        "evidence": "Главный бухгалтер сверил закрытую ОСВ с источником",
    }
    entries_before = await db.scalar(select(func.count()).select_from(Entry))
    response = await client.post(f"/accounting/organizations/{book[0]}/reconciliation/confirm", json=data)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["accepted_by_accountant"] is True and receipt["cutover_ready"] is True
    assert receipt["erp_ledger_verified"] is True
    assert receipt["already_confirmed"] is False
    assert await db.scalar(select(func.count()).select_from(Entry)) == entries_before
    assert await db.scalar(select(func.count()).select_from(ReconciliationReceipt)) == 1

    async def changed_ledger(_session, _org_id, _start, _end):
        raise AssertionError("Exact replay must not reread the current ledger")
    monkeypatch.setattr(reconciliation, "erp_snapshot", changed_ledger)
    replay = await client.post(f"/accounting/organizations/{book[0]}/reconciliation/confirm", json=data)
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_confirmed"] is True
    assert await db.scalar(select(func.count()).select_from(ReconciliationReceipt)) == 1

    monkeypatch.setattr(reconciliation, "erp_snapshot", matching_ledger)
    duplicate_key = {**data, "request_key": "00000000-0000-4000-8000-000000000002"}
    assert (await client.post(f"/accounting/organizations/{book[0]}/reconciliation/confirm", json=duplicate_key)).status_code == 422
    different_evidence = {**duplicate_key, "evidence": "Другая формулировка подтверждения бухгалтером"}
    assert (await client.post(f"/accounting/organizations/{book[0]}/reconciliation/confirm", json=different_evidence)).status_code == 422


async def test_equal_uploaded_csv_cannot_certify_a_different_erp_ledger(client, db, book):
    from sqlalchemy import func, select

    from modules.accounting.models import ReconciliationReceipt

    raw = snapshot(org=str(book[0]), status="closed_periods", pending="0")
    encoded = base64.b64encode(raw).decode()
    path = f"/accounting/organizations/{book[0]}/reconciliation"
    preview = await client.post(path, json={"left_base64": encoded, "right_base64": encoded})
    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] == "no_numeric_differences"
    assert preview.json()["erp_ledger_verified"] is False
    assert preview.json()["cutover_ready"] is False
    assert preview.json()["eligibility_blockers"] == ["erp_snapshot_mismatch"]
    confirmed = await client.post(f"{path}/confirm", json={
        "request_key": "00000000-0000-4000-8000-000000000024",
        "left_base64": encoded, "right_base64": encoded,
        "evidence": "Проверка поддельной пары без проводок в ERP",
    })
    assert confirmed.status_code == 422
    assert await db.scalar(select(func.count()).select_from(ReconciliationReceipt)) == 0


async def test_closed_erp_export_can_be_compared_and_accepted_without_reposting(
        client, db, book, posting, opening_package):
    from sqlalchemy import func, select

    from modules.accounting import service
    from modules.accounting.models import Entry

    prefix = f"/accounting/organizations/{book[0]}"
    package = opening_package([posting("opening-osv", "51", "80", opening=True)],
                              batch="opening-osv-batch")
    assert (await client.post(f"{prefix}/imports/confirm", json=package)).status_code == 200
    periods = (await client.get(f"{prefix}/periods")).json()
    close = {"expected_generation": periods[0]["generation"],
             "evidence": {step: "Synthetic closed report review" for step in service.CLOSE_STEPS}}
    assert (await client.post(f"{prefix}/periods/2026-09/close", json=close)).status_code == 200
    export = await client.get(f"{prefix}/reconciliation/erp-osv.csv?start=2026-09-01&end=2026-09-30")
    assert export.status_code == 200, export.text
    parsed = parse_snapshot(export.content)
    assert parsed["status"] == "closed_periods"
    assert len(parsed["balances"]) == 2
    encoded = base64.b64encode(export.content).decode()
    before = await db.scalar(select(func.count()).select_from(Entry))
    preview = await client.post(f"{prefix}/reconciliation", json={
        "left_base64": encoded, "right_base64": encoded,
    })
    assert preview.status_code == 200, preview.text
    assert preview.json()["erp_ledger_verified"] is True
    assert preview.json()["cutover_ready"] is True
    accepted = await client.post(f"{prefix}/reconciliation/confirm", json={
        "request_key": "00000000-0000-4000-8000-000000000025",
        "left_base64": encoded, "right_base64": encoded,
        "evidence": "Synthetic accountant accepted exact ERP export",
    })
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["erp_ledger_verified"] is True
    assert accepted.json()["snapshot"]["erp_ledger_sha256"] == parsed["sha256"]
    assert await db.scalar(select(func.count()).select_from(Entry)) == before


async def test_reconciliation_confirmation_rejects_open_or_different_reports(client, book):
    raw = snapshot(org=str(book[0]), status="preliminary", pending="0")
    data = {
        "request_key": "00000000-0000-4000-8000-000000000003",
        "left_base64": base64.b64encode(raw).decode(),
        "right_base64": base64.b64encode(raw.replace(b"preliminary", b"closed_periods")).decode(),
        "evidence": "Недостаточное основание для подтверждения",
    }
    response = await client.post(f"/accounting/organizations/{book[0]}/reconciliation/confirm", json=data)
    assert response.status_code == 422 and "не готова" in response.text
