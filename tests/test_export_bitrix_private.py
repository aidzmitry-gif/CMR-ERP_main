"""Contract checks for the server-only Bitrix metadata staging path."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import requests

SPEC = importlib.util.spec_from_file_location(
    "export_bitrix_private", Path(__file__).parents[1] / "scripts" / "export_bitrix_private.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

WEBHOOK = "https://microchops.bitrix24.by/rest/1/TEST_SECRET"


class Response:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


class Session:
    def __init__(self):
        self.calls = []

    def post(self, url, *, json, timeout, allow_redirects):
        assert not allow_redirects
        method = url.rsplit("/", 1)[-1].removesuffix(".json")
        self.calls.append((method, json))
        if method.endswith(".fields"):
            return Response({"result": {"ID": {"isMultiple": False},
                                        "PHONE": {"isMultiple": True},
                                        "EMAIL": {"isMultiple": True},
                                        "COMPANY_IDS": {"isMultiple": True}}})
        if method == "crm.deal.list":
            return Response({"result": [{"ID": "11", "TITLE": "Secret Deal", "COMPANY_ID": "51"}]})
        if method == "crm.lead.list":
            return Response({"result": [{"ID": "31", "NAME": "Private Person"}]})
        if method == "crm.contact.list":
            assert {"PHONE", "EMAIL"}.issubset(json["select"])
            assert "COMPANY_IDS" not in json["select"]
            return Response({"result": [{"ID": "21", "PHONE": "SECRET_PHONE"}]})
        if method in {"crm.contact.company.items.get", "crm.deal.contact.items.get"}:
            return Response({"result": []})
        if method == "crm.activity.list":
            assert {"COMMUNICATIONS", "FILES", "STORAGE_ELEMENT_IDS"}.issubset(json["select"])
        if method == "crm.requisite.list":
            assert json["filter"] == {"ENTITY_TYPE_ID": 4, "@ENTITY_ID": ["51"]}
            return Response({"result": [{"ID": "41", "ENTITY_ID": "51", "RQ_INN": "123456789"}]})
        if method == "crm.company.list":
            assert json["filter"] == {"@ID": ["51"]}
            assert json["select"] == ["ID", "TITLE"]
            return Response({"result": [{"ID": "51", "TITLE": "Evidence Name"}]})
        if method == "crm.deal.productrows.get":
            return Response({"result": [{"ID": "61", "PRODUCT_ID": "71"}]})
        if method == "crm.product.get":
            assert json == {"id": 71}
            return Response({"result": {"ID": "71", "XML_ID": "1C-REF-71",
                                        "CODE": "SKU-71", "NAME": "PRIVATE_PRODUCT"}})
        if method == "crm.timeline.comment.list":
            return Response({"result": []})
        if method == "tasks.task.list":
            assert json == {"order": {"ID": "asc"}, "filter": {}, "select": ["ID"], "start": 0}
            return Response({"result": {"tasks": [{"id": "101"}]}, "total": 1})
        if method == "tasks.task.get":
            assert json["taskId"] == 101
            assert {"UF_CRM_TASK", "UF_TASK_WEBDAV_FILES"}.issubset(json["select"])
            return Response({"result": {"task": {"id": "101", "title": "SECRET_TASK_TITLE",
                                                 "ufCrmTask": ["D_11"],
                                                 "ufTaskWebdavFiles": [1065]}}})
        if method == "crm.stagehistory.list":
            if json["entityTypeId"] == 1:
                assert "STATUS_ID" in json["select"]
                assert "STAGE_ID" not in json["select"]
            return Response({"result": {"items": [{"ID": "81" if json["entityTypeId"] == 2 else "82"}]}})
        return Response({"result": []})


def test_server_staging_requests_only_company_name_evidence_and_prints_no_rows(tmp_path, capsys):
    session = Session()
    output = tmp_path / "private"
    summary = module.export(WEBHOOK, output, session=session)
    assert sum(method == "crm.company.list" for method, _ in session.calls) == 1
    assert summary["deals"]["records"] == 1
    assert summary["deal_product_rows"]["records"] == 1
    assert summary["product_catalog_evidence"]["records"] == 1
    assert summary["contacts"]["records"] == 1
    assert summary["requisites"]["records"] == 1
    assert summary["field_schemas"]["records"] == 3
    assert summary["contact_company_links"]["records"] == 1
    assert summary["deal_contact_links"]["records"] == 1
    assert any(method == "crm.contact.company.items.get" for method, _ in session.calls)
    assert any(method == "crm.deal.contact.items.get" for method, _ in session.calls)
    assert summary["company_name_evidence"]["records"] == 1
    assert summary["tasks"]["records"] == 1
    assert summary["unresolved_company_ids"]["records"] == 0
    assert not (output / "companies").exists()
    assert "SECRET_PHONE" not in capsys.readouterr().out
    assert "SECRET_TASK_TITLE" not in (output / "manifest.json").read_text(encoding="utf-8")
    assert "PRIVATE_PRODUCT" not in (output / "manifest.json").read_text(encoding="utf-8")
    assert "SECRET_PHONE" not in (output / "manifest.json").read_text(encoding="utf-8")
    assert any("SECRET_PHONE" in path.read_text(encoding="utf-8") for path in (output / "contacts").glob("*.json"))
    assert any("SECRET_TASK_TITLE" in path.read_text(encoding="utf-8") for path in (output / "tasks").glob("*.json"))
    assert any("1C-REF-71" in path.read_text(encoding="utf-8") for path in (output / "product_catalog_evidence").glob("*.json"))
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8")) == summary
    with pytest.raises(module.ExportError, match="OUTPUT_NOT_EMPTY"):
        module.export(WEBHOOK, output, session=session)


def test_webhook_host_and_method_allowlist():
    for bad in ("", "http://microchops.bitrix24.by/rest/1/secret",
                "https://other.bitrix24.by/rest/1/secret",
                "https://microchops.bitrix24.by/rest/1/secret?x=1"):
        with pytest.raises(module.ExportError, match="BAD_WEBHOOK_CONFIGURATION"):
            module.BitrixReadOnly(bad)
    with pytest.raises(module.ExportError, match="METHOD_NOT_ALLOWED"):
        module.BitrixReadOnly(WEBHOOK).call("crm.company.get", {})
    with pytest.raises(module.ExportError, match="COMPANY_SCOPE_VIOLATION"):
        module.BitrixReadOnly(WEBHOOK).call("crm.company.list", {"filter": {"@ID": ["51"]}, "select": ["*"]})
    with pytest.raises(module.ExportError, match="PRODUCT_SCOPE_VIOLATION"):
        module.BitrixReadOnly(WEBHOOK).call("crm.product.get", {"id": [71]})


def test_referenced_catalog_product_is_fetched_once_and_must_match_id(tmp_path):
    class ReusedProductSession(Session):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/crm.deal.productrows.get.json"):
                return Response({"result": [{"ID": "61", "PRODUCT_ID": 71},
                                            {"ID": "62", "PRODUCT_ID": "71"},
                                            {"ID": "63", "PRODUCT_ID": 0}]})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    session = ReusedProductSession()
    summary = module.export(WEBHOOK, tmp_path / "private", session=session)
    assert summary["product_catalog_evidence"]["records"] == 1
    assert sum(method == "crm.product.get" for method, _ in session.calls) == 1

    class WrongProductSession(Session):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/crm.product.get.json"):
                return Response({"result": {"ID": "72", "XML_ID": "OTHER"}})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    with pytest.raises(module.ExportError, match="PRODUCT_DETAIL_MISMATCH"):
        module.export(WEBHOOK, tmp_path / "wrong", session=WrongProductSession())
    assert not (tmp_path / "wrong" / "manifest.json").exists()


@pytest.mark.parametrize("bad_row", [
    {"ID": "", "PRODUCT_ID": "71"},
    {"ID": "0", "PRODUCT_ID": "71"},
    {"ID": "²", "PRODUCT_ID": "71"},
    {"ID": "61", "PRODUCT_ID": "-1"},
    {"ID": "61", "PRODUCT_ID": "²"},
    {"ID": "61", "PRODUCT_ID": True},
    {"ID": "61", "PRODUCT_ID": "71", "OWNER_ID": "999"},
    {"ID": "61", "PRODUCT_ID": "71", "OWNER_TYPE": "L"},
])
def test_product_row_with_invalid_catalog_or_deal_link_fails_closed(tmp_path, bad_row):
    class BadLinkSession(Session):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/crm.deal.productrows.get.json"):
                return Response({"result": [bad_row]})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    output = tmp_path / "private"
    with pytest.raises(module.ExportError, match="BAD_PRODUCT_ROW_LINK"):
        module.export(WEBHOOK, output, session=BadLinkSession())
    assert not (output / "manifest.json").exists()


def test_duplicate_product_row_id_fails_before_sealing_source(tmp_path):
    class DuplicateRowSession(Session):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/crm.deal.productrows.get.json"):
                return Response({"result": [{"ID": "061", "PRODUCT_ID": 71},
                                            {"ID": "61", "PRODUCT_ID": 71}]})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    output = tmp_path / "private"
    with pytest.raises(module.ExportError, match="BAD_PRODUCT_ROW_LINK"):
        module.export(WEBHOOK, output, session=DuplicateRowSession())
    assert not (output / "manifest.json").exists()


def test_pages_reject_repeated_offset_without_leaking_response():
    class RepeatingSession(Session):
        def post(self, url, *, json, timeout, allow_redirects):
            return Response({"result": [{"ID": "1", "TITLE": "Private"}], "next": 50})

    with pytest.raises(module.ExportError, match="BAD_NEXT_OFFSET") as exc:
        list(module.BitrixReadOnly(WEBHOOK, RepeatingSession()).pages("crm.deal.list", {}))
    assert "Private" not in str(exc.value)


def test_api_error_and_http_redirect_are_sanitized():
    class FailureSession(Session):
        def __init__(self, response):
            self.response = response

        def post(self, url, *, json, timeout, allow_redirects):
            return self.response

    with pytest.raises(module.ExportError, match="API_ERROR_OR_MISSING_RESULT") as exc:
        module.BitrixReadOnly(WEBHOOK, FailureSession(Response({"error": "Private"}))).call("crm.deal.list", {})
    assert "Private" not in str(exc.value)
    redirect = Response({"result": []})
    redirect.status_code = 302
    with pytest.raises(module.ExportError, match="HTTP_302"):
        module.BitrixReadOnly(WEBHOOK, FailureSession(redirect)).call("crm.deal.list", {})


def test_pages_reject_missing_rows_even_when_next_is_absent():
    class ShortSession(Session):
        def post(self, url, *, json, timeout, allow_redirects):
            return Response({"result": [{"ID": "1"}], "total": 2})

    with pytest.raises(module.ExportError, match="INCOMPLETE_PAGE_SET"):
        list(module.BitrixReadOnly(WEBHOOK, ShortSession()).pages("crm.deal.list", {}))


def test_missing_company_name_is_recorded_as_private_unresolved_id(tmp_path):
    class MissingNameSession(Session):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/crm.company.list.json"):
                return Response({"result": []})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    output = tmp_path / "private"
    summary = module.export(WEBHOOK, output, session=MissingNameSession())
    assert summary["company_name_evidence"]["records"] == 0
    assert summary["unresolved_company_ids"]["records"] == 1
    assert "\"company_id\":" not in (output / "manifest.json").read_text(encoding="utf-8")


def test_activity_only_company_is_included_in_name_evidence(tmp_path):
    class ActivityCompanySession(Session):
        def __init__(self):
            super().__init__()
            self.company_requests = []

        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/crm.activity.list.json"):
                return Response({"result": [{"ID": "91", "OWNER_TYPE_ID": "4", "OWNER_ID": "99",
                                             "COMMUNICATIONS": [{"ENTITY_TYPE_ID": "4", "ENTITY_ID": "98"}]}]})
            if url.endswith("/crm.company.list.json"):
                ids = json["filter"]["@ID"]
                self.company_requests.extend(ids)
                return Response({"result": [{"ID": value, "TITLE": "Evidence"} for value in ids]})
            if url.endswith("/crm.requisite.list.json"):
                return Response({"result": []})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    session = ActivityCompanySession()
    summary = module.export(WEBHOOK, tmp_path / "private", session=session)
    assert {"51", "98", "99"}.issubset(session.company_requests)
    assert summary["company_name_evidence"]["records"] == 3


def test_comment_without_id_fails_closed(tmp_path):
    class BadCommentSession(Session):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/crm.timeline.comment.list.json"):
                return Response({"result": [{"ENTITY_ID": "11", "ENTITY_TYPE": "deal", "COMMENT": "Private"}]})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    with pytest.raises(module.ExportError, match="COMMENT_WITHOUT_ID") as exc:
        module.export(WEBHOOK, tmp_path / "private", session=BadCommentSession())
    assert "Private" not in str(exc.value)


def test_task_list_paginates_all_ids_and_rejects_drift():
    class TaskPages(Session):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/tasks.task.list.json"):
                start = json["start"]
                assert start in (0, 50)
                ids = range(1, 51) if start == 0 else range(51, 52)
                return Response({"result": {"tasks": [{"id": str(value)} for value in ids]},
                                 "total": 51})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    assert list(module.BitrixReadOnly(WEBHOOK, TaskPages()).task_ids()) == [str(i) for i in range(1, 52)]

    class ChangedTotal(TaskPages):
        def post(self, url, *, json, timeout, allow_redirects):
            response = super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)
            if url.endswith("/tasks.task.list.json") and json["start"] == 50:
                response.data["total"] = 52
            return response

    with pytest.raises(module.ExportError, match="SOURCE_CHANGED_DURING_EXPORT"):
        list(module.BitrixReadOnly(WEBHOOK, ChangedTotal()).task_ids())


def test_task_detail_id_mismatch_fails_without_value_leak(tmp_path):
    class WrongTask(Session):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/tasks.task.get.json"):
                return Response({"result": {"task": {"id": "999", "title": "PRIVATE_TASK"}}})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    with pytest.raises(module.ExportError, match="TASK_DETAIL_MISMATCH") as exc:
        module.export(WEBHOOK, tmp_path / "private", session=WrongTask())
    assert "PRIVATE_TASK" not in str(exc.value)


def _binary_metadata(root, *, call_url="https://microchops.bitrix24.by/rest/download.json?token=PRIVATE",
                     crm_file_items=None, call_record_file_id=None, source_call_id=None,
                     call_owner_type=None, call_owner_id=None, call_user_id=None,
                     comments=None, deals=None, leads=None, tasks=None):
    root.mkdir()
    call = {"ID": "10", "CALL_RECORD_URL": call_url}
    if call_record_file_id is not None:
        call["RECORD_FILE_ID"] = call_record_file_id
    if source_call_id is not None:
        call["CALL_ID"] = source_call_id
    if call_owner_type is not None:
        call["CRM_ENTITY_TYPE"] = call_owner_type
    if call_owner_id is not None:
        call["CRM_ENTITY_ID"] = call_owner_id
    if call_user_id is not None:
        call["PORTAL_USER_ID"] = call_user_id
    rows = {
        "deals": [{"ID": "11"}] if deals is None else deals,
        "leads": [] if leads is None else leads,
        "timeline_comments": ([{"ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "11",
                              "FILES": {"3": {"id": 3, "name": "PRIVATE_NAME"}}}]
                              if comments is None else comments),
        "tasks": ([{"id": "8", "ufTaskWebdavFiles": ["n9"]}]
                  if tasks is None else tasks),
        "calls": [call],
        "crm_file_items": crm_file_items or [],
    }
    summary = {}
    for name, dataset_rows in rows.items():
        dataset = module.Dataset(root, name)
        for index, row in enumerate(dataset_rows):
            dataset.add(str(row.get("ID")) if name == "calls" else str(index), row)
        summary[name] = dataset.summary()
    (root / "manifest.json").write_text(json.dumps(summary), encoding="utf-8")


class BinaryResponse:
    status_code = 200

    def __init__(self, body=b"DATA", *, content_type="application/octet-stream", length=None,
                 disposition=None):
        self.body = body
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(body) if length is None else length)}
        if disposition is not None:
            self.headers["Content-Disposition"] = disposition
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.body[:2]
        yield self.body[2:]

    def close(self):
        self.closed = True


class BinarySession(Session):
    def __init__(self, *, response=None):
        super().__init__()
        self.downloads = []
        self.response = response or BinaryResponse()

    def post(self, url, *, json, timeout, allow_redirects):
        if url.endswith("/voximplant.statistic.get.json"):
            assert json == {"FILTER": {"ID": [10]}, "SORT": "ID", "ORDER": "ASC"}
            return Response({"result": [{"ID": "10", "CALL_RECORD_URL":
                "https://microchops.bitrix24.by/rest/download.json?token=FRESH_CALL"}]})
        if url.endswith("/disk.attachedObject.get.json"):
            assert json == {"id": 9}
            return Response({"result": {"ID": "9", "OBJECT_ID": "3",
                                        "ENTITY_TYPE": "tasks_task", "ENTITY_ID": "8"}})
        if url.endswith("/disk.file.get.json"):
            assert json == {"id": 3}
            return Response({"result": {"ID": "3", "NAME": "PRIVATE_NAME", "SIZE": "4",
                                        "DOWNLOAD_URL": "https://microchops.bitrix24.by/rest/download.json?token=FILE_SECRET"}})
        raise AssertionError("unexpected REST method")

    def get(self, url, *, stream, timeout, allow_redirects, headers):
        assert stream and not allow_redirects
        assert headers["User-Agent"] == "CRM-LIVE-001/1.0"
        assert headers["Referer"] == "https://microchops.bitrix24.by/"
        assert headers["Accept"] == "*/*"
        self.downloads.append(url)
        return self.response if len(self.downloads) == 1 else BinaryResponse(b"CALL")


def test_private_binary_phase_resolves_task_comment_and_call_without_duplicate_file(tmp_path, capsys):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata)
    session = BinarySession()
    output = tmp_path / "binaries"
    summary = module.export_binaries(WEBHOOK, metadata, output, session=session)
    assert summary["binary_files"]["records"] == 2
    assert summary["binary_inventory"]["records"] == 2
    assert summary["binary_links"]["records"] == 3
    assert len(session.downloads) == 2
    assert "FRESH_CALL" in session.downloads[-1]
    assert "token=PRIVATE" not in session.downloads[-1]
    assert sorted(path.read_bytes() for path in (output / "binary_files").glob("*.bin")) == [b"CALL", b"DATA"]
    manifest = (output / "manifest.json").read_text(encoding="utf-8")
    assert "PRIVATE" not in manifest + capsys.readouterr().out
    assert "FILE_SECRET" not in manifest
    assert session.response.closed

    links, inventory = module._verified_binary_snapshot(output.resolve())
    assert len(links) == 3
    assert set(inventory) == {"disk:3", "call:10"}


def test_binary_snapshot_rejects_changed_or_unlisted_bytes(tmp_path):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata)
    output = (tmp_path / "binaries").resolve()
    module.export_binaries(WEBHOOK, metadata, output, session=BinarySession())
    paths = sorted((output / "binary_files").glob("*.bin"))
    paths[0].write_bytes(b"XXXX")
    with pytest.raises(module.ExportError, match="BINARY_SNAPSHOT_CHANGED"):
        module._verified_binary_snapshot(output)
    paths[0].write_bytes(b"DATA" if paths[0].name == module.hashlib.sha256(b"disk:3").hexdigest() + ".bin" else b"CALL")
    (output / "binary_files" / ("0" * 64 + ".bin")).write_bytes(b"EXTRA")
    with pytest.raises(module.ExportError, match="BINARY_SNAPSHOT_CHANGED"):
        module._verified_binary_snapshot(output)


def test_binary_snapshot_rejects_extra_root_file(tmp_path):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata)
    output = (tmp_path / "binaries").resolve()
    module.export_binaries(WEBHOOK, metadata, output, session=BinarySession())
    (output / "unexpected.txt").write_text("PRIVATE_EXTRA", encoding="utf-8")
    with pytest.raises(module.ExportError, match="BAD_BINARY_SNAPSHOT"):
        module._verified_binary_snapshot(output)


def test_comment_binary_links_retain_owner_and_dedupe_shared_file(tmp_path):
    comments = [
        {"ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "11", "FILES": {"3": {"id": 3}}},
        {"ID": "7", "ENTITY_TYPE": "lead", "ENTITY_ID": "12", "FILES": {"3": {"id": 3}}},
    ]
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata, comments=comments, leads=[{"ID": "12"}])
    session = BinarySession()
    output = tmp_path / "binaries"
    summary = module.export_binaries(WEBHOOK, metadata, output, session=session)
    assert summary["binary_files"]["records"] == 2
    assert len(session.downloads) == 2
    links = [json.loads(path.read_text(encoding="utf-8"))
             for path in (output / "binary_links").glob("*.json")]
    comment_links = [row for row in links if row["source"] == "comment"]
    assert {(row["entity_type"], row["entity_id"], row["source_id"], row["file_id"])
            for row in comment_links} == {("deal", "11", "7", "3"), ("lead", "12", "7", "3")}
    assert {row["binary_key"] for row in comment_links} == {"disk:3"}


@pytest.mark.parametrize("comments,deals,leads,error", [
    ([{"ID": "7", "ENTITY_TYPE": "deal", "FILES": {"3": {"id": 3}}}], None, None,
     "BAD_COMMENT_OWNER"),
    ([{"ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "99", "FILES": {"3": {"id": 3}}}],
     None, None, "COMMENT_WRONG_OWNER"),
    ([{"ID": "7", "ENTITY_TYPE": "contact", "ENTITY_ID": "11", "FILES": {"3": {"id": 3}}}],
     None, None, "BAD_COMMENT_OWNER"),
    ([{"ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "11", "FILES": {"4": {"id": 3}}}],
     None, None, "COMMENT_FILE_ID_MISMATCH"),
    ([{"ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "11", "FILES": []}],
     None, None, "BAD_COMMENT_FILES"),
    ([{"ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "11", "FILES": {"3": {"id": 3}}},
      {"ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "11", "FILES": {"3": {"id": 3}}}],
     None, None, "DUPLICATE_COMMENT_ID"),
])
def test_comment_binary_owner_or_file_mismatch_fails_before_download(
    tmp_path, comments, deals, leads, error,
):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata, comments=comments, deals=deals, leads=leads)
    session = BinarySession()
    output = tmp_path / "binaries"
    with pytest.raises(module.ExportError, match=error):
        module.export_binaries(WEBHOOK, metadata, output, session=session)
    assert session.downloads == []
    assert not (output / "manifest.json").exists()


def test_call_recording_refresh_checks_source_identity_and_file_id(tmp_path):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata, source_call_id="call-10", call_record_file_id=42)

    class ChangedCall(BinarySession):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/voximplant.statistic.get.json"):
                return Response({"result": [{"ID": "10", "CALL_ID": "call-10",
                    "RECORD_FILE_ID": 43, "CALL_RECORD_URL":
                    "https://microchops.bitrix24.by/rest/download.json?token=NEW"}]})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    session = ChangedCall()
    output = tmp_path / "binaries"
    with pytest.raises(module.ExportError, match="CALL_RECORD_CHANGED"):
        module.export_binaries(WEBHOOK, metadata, output, session=session)
    assert all("token=NEW" not in url for url in session.downloads)
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize(("field", "changed"), [
    ("CRM_ENTITY_TYPE", "COMPANY"),
    ("CRM_ENTITY_ID", "12"),
    ("PORTAL_USER_ID", "6"),
])
def test_call_recording_refresh_preserves_owner_and_rejects_owner_drift(
    tmp_path, field, changed
):
    metadata = tmp_path / "metadata"
    _binary_metadata(
        metadata, source_call_id="call-10", call_owner_type="CONTACT",
        call_owner_id="11", call_user_id="5",
    )

    class SameOwner(BinarySession):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/voximplant.statistic.get.json"):
                return Response({"result": [{
                    "ID": "10", "CALL_ID": "call-10", "CRM_ENTITY_TYPE": "CONTACT",
                    "CRM_ENTITY_ID": "11", "PORTAL_USER_ID": "5",
                    "CALL_RECORD_URL": "https://microchops.bitrix24.by/rest/download.json?token=FRESH_CALL",
                }]})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    output = tmp_path / "binaries"
    session = SameOwner()
    module.export_binaries(WEBHOOK, metadata, output, session=session)
    call_link = next(
        row for row in module._staged_rows(output, "binary_links")
        if row["source"] == "call"
    )
    assert {key: call_link[key] for key in (
        "source_id", "call_id", "entity_type", "entity_id", "portal_user_id"
    )} == {
        "source_id": "10", "call_id": "call-10", "entity_type": "CONTACT",
        "entity_id": "11", "portal_user_id": "5",
    }
    assert "FRESH_CALL" not in json.dumps(call_link)

    class ChangedOwner(SameOwner):
        def post(self, url, *, json, timeout, allow_redirects):
            response = super().post(url, json=json, timeout=timeout,
                                    allow_redirects=allow_redirects)
            if url.endswith("/voximplant.statistic.get.json"):
                response.data["result"][0][field] = changed
            return response

    drift = ChangedOwner()
    with pytest.raises(module.ExportError, match="CALL_RECORD_CHANGED"):
        module.export_binaries(WEBHOOK, metadata, tmp_path / "drift", session=drift)
    assert all("FRESH_CALL" not in url for url in drift.downloads)


@pytest.mark.parametrize(("field", "changed"), [
    ("CALL_ID", "late-call-id"),
    ("RECORD_FILE_ID", 42),
])
def test_call_recording_refresh_rejects_new_identity_after_snapshot(
    tmp_path, field, changed
):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata)

    class ChangedCall(BinarySession):
        def post(self, url, *, json, timeout, allow_redirects):
            response = super().post(url, json=json, timeout=timeout,
                                    allow_redirects=allow_redirects)
            if url.endswith("/voximplant.statistic.get.json"):
                response.data["result"][0][field] = changed
            return response

    session = ChangedCall()
    with pytest.raises(module.ExportError, match="CALL_RECORD_CHANGED"):
        module.export_binaries(WEBHOOK, metadata, tmp_path / "binaries", session=session)
    assert all("FRESH_CALL" not in url for url in session.downloads)


@pytest.mark.parametrize(("field", "argument", "error"), [
    ("CRM_ENTITY_TYPE", "call_owner_type", "BAD_CALL_OWNER_TYPE"),
    ("CRM_ENTITY_ID", "call_owner_id", "BAD_CALL_OWNER_ID"),
    ("PORTAL_USER_ID", "call_user_id", "BAD_CALL_USER_ID"),
])
@pytest.mark.parametrize("invalid", [False, 0, [], {}])
def test_call_recording_rejects_invalid_staged_owner_before_download(
    tmp_path, field, argument, error, invalid
):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata, **{argument: invalid})
    session = BinarySession()
    with pytest.raises(module.ExportError, match=error):
        module.export_binaries(WEBHOOK, metadata, tmp_path / "binaries", session=session)
    assert session.downloads == []


@pytest.mark.parametrize("field", [
    "CRM_ENTITY_TYPE", "CRM_ENTITY_ID", "PORTAL_USER_ID",
])
@pytest.mark.parametrize("invalid", [False, 0, [], {}])
def test_call_recording_rejects_invalid_fresh_owner_before_recording_download(
    tmp_path, field, invalid
):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata)

    class InvalidOwner(BinarySession):
        def post(self, url, *, json, timeout, allow_redirects):
            response = super().post(url, json=json, timeout=timeout,
                                    allow_redirects=allow_redirects)
            if url.endswith("/voximplant.statistic.get.json"):
                response.data["result"][0][field] = invalid
            return response

    session = InvalidOwner()
    with pytest.raises(module.ExportError, match="CALL_RECORD_CHANGED"):
        module.export_binaries(WEBHOOK, metadata, tmp_path / "binaries", session=session)
    assert all("FRESH_CALL" not in url for url in session.downloads)


@pytest.mark.parametrize("bad_call_id", [False, 0])
def test_call_recording_rejects_falsy_invalid_source_call_id_before_download(
    tmp_path, bad_call_id
):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata, source_call_id=bad_call_id)
    session = BinarySession()
    with pytest.raises(module.ExportError, match="BAD_CALL_ID"):
        module.export_binaries(WEBHOOK, metadata, tmp_path / "binaries", session=session)
    assert not session.downloads


@pytest.mark.parametrize("bad_call_id", [False, 0])
def test_call_recording_rejects_falsy_invalid_fresh_call_id_before_recording_download(
    tmp_path, bad_call_id
):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata)

    class InvalidCall(BinarySession):
        def post(self, url, *, json, timeout, allow_redirects):
            response = super().post(url, json=json, timeout=timeout,
                                    allow_redirects=allow_redirects)
            if url.endswith("/voximplant.statistic.get.json"):
                response.data["result"][0]["CALL_ID"] = bad_call_id
            return response

    session = InvalidCall()
    with pytest.raises(module.ExportError, match="CALL_RECORD_CHANGED"):
        module.export_binaries(WEBHOOK, metadata, tmp_path / "binaries", session=session)
    assert all("FRESH_CALL" not in url for url in session.downloads)


def test_call_with_record_file_id_retries_fresh_url_and_reports_unavailable(tmp_path):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata, call_url=None, call_record_file_id=42)

    class Unavailable(BinarySession):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/voximplant.statistic.get.json"):
                return Response({"result": [{"ID": "10", "RECORD_FILE_ID": 42,
                                            "CALL_RECORD_URL": ""}]})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    session = Unavailable()
    summary = module.export_binaries(WEBHOOK, metadata, tmp_path / "binaries", session=session)
    assert summary["unavailable_recordings"]["records"] == 1
    assert summary["binary_files"]["records"] == 1
    assert len(session.downloads) == 1


def test_call_refresh_rejects_broad_query():
    with pytest.raises(module.ExportError, match="CALL_SCOPE_VIOLATION"):
        module.BitrixReadOnly(WEBHOOK).call("voximplant.statistic.get", {
            "FILTER": {"PHONE_NUMBER": "*"}, "SORT": "ID", "ORDER": "ASC",
        })


def _private_stage_sources(bitrix_root, onec_root, *, with_products=True,
                           product_envelopes=None, catalog_rows=None,
                           comments=None, tasks=None, task_keys=None,
                           deal_rows=None, calls=None):
    bitrix_root.mkdir()
    bitrix_summary = {}
    for name in sorted(module.PRIVATE_BITRIX_DATASETS):
        dataset = module.Dataset(bitrix_root, name)
        if name == "deal_product_rows":
            envelopes = product_envelopes
            if envelopes is None:
                envelopes = ([{"deal_id": "1", "rows": [{
                    "ID": "9", "PRODUCT_ID": "7", "PRODUCT_NAME": "PRIVATE_ROW_NAME",
                }]}] if with_products else [{"deal_id": "1", "rows": []}])
            for envelope in envelopes:
                dataset.add(str(envelope.get("deal_id") or ""), envelope)
        elif name == "product_catalog_evidence":
            evidence_rows = catalog_rows
            if evidence_rows is None:
                evidence_rows = ([{"ID": "7", "XML_ID": "ref-1", "CODE": "SKU-1",
                                   "NAME": "PRIVATE_PRODUCT"}] if with_products else [])
            for evidence in evidence_rows:
                dataset.add(str(evidence.get("ID") or ""), evidence)
        elif name == "deals":
            rows = deal_rows if deal_rows is not None else [
                {"ID": "1", "TITLE": "PRIVATE_SOURCE"},
            ]
            for row in rows:
                dataset.add(str(row.get("ID") or ""), row)
        elif name == "deal_stage_history":
            dataset.add("81", {"ID": "81", "TYPE_ID": "1", "OWNER_ID": "1",
                               "CREATED_TIME": "2025-12-01T09:00:00+03:00",
                               "CATEGORY_ID": "0", "STAGE_SEMANTIC_ID": "P",
                               "STAGE_ID": "NEW"})
        elif name == "timeline_comments":
            for index, row in enumerate(comments if comments is not None else [{
                "ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "1",
                "CREATED": "2025-12-01T09:00:00+03:00", "AUTHOR_ID": "1",
                "COMMENT": "PRIVATE_COMMENT", "FILES": {},
            }]):
                dataset.add(f"{row['ENTITY_TYPE']}:{row['ID']}:{index}", row)
        elif name == "tasks":
            for index, row in enumerate(tasks or []):
                key = task_keys[index] if task_keys is not None else (
                    row.get("id") or row.get("ID") or str(index)
                )
                dataset.add(str(key), row)
        elif name == "calls":
            call_rows = calls if calls is not None else [
                {"ID": "1", "TITLE": "PRIVATE_SOURCE"},
            ]
            for row in call_rows:
                dataset.add(str(row.get("ID") or ""), row)
        elif name in module.PRIVATE_CACHE_MAP and not name.startswith("Catalog_") and name not in {
            "deals", "deal_product_rows", "product_catalog_evidence",
        }:
            dataset.add("1", {"ID": "1", "TITLE": "PRIVATE_SOURCE"})
        bitrix_summary[name] = dataset.summary()
    (bitrix_root / "manifest.json").write_text(
        json.dumps(bitrix_summary), encoding="utf-8")

    onec_root.mkdir()
    onec_summary = {}
    for name in sorted(module.PRIVATE_ONEC_DATASETS):
        dataset = module.Dataset(onec_root, name)
        dataset.add("ref-1", {"Ref_Key": "ref-1", "Description": "PRIVATE_1C"})
        onec_summary[name] = dataset.summary()
    (onec_root / "manifest.json").write_text(json.dumps(onec_summary), encoding="utf-8")


CALL_RECORD_URL = (
    "https://microchops.bitrix24.by/rest/download.json?token=SOURCE_SIGNED_TOKEN"
)


def _call_binary_stage_inputs(tmp_path, *, source_call_overrides=None, comments=None):
    tmp_path = tmp_path.resolve()
    comments = comments or []
    call = {
        "ID": "10", "CALL_ID": "call-10", "RECORD_FILE_ID": "42",
        "CALL_RECORD_URL": CALL_RECORD_URL, "CRM_ENTITY_TYPE": "CONTACT",
        "CRM_ENTITY_ID": "11", "PORTAL_USER_ID": "5",
    }
    source_call = {**call, **(source_call_overrides or {})}
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(
        bitrix_root, onec_root, with_products=False, comments=comments, calls=[source_call]
    )
    metadata = tmp_path / "binary_metadata"
    _binary_metadata(
        metadata, call_url=CALL_RECORD_URL, source_call_id="call-10",
        call_record_file_id=42, call_owner_type="CONTACT", call_owner_id="11",
        call_user_id="5", comments=comments, deals=[{"ID": "11"}], tasks=[],
    )

    class SameCallIdentity(BinarySession):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/voximplant.statistic.get.json"):
                return Response({"result": [{
                    "ID": "10", "CALL_ID": "call-10", "RECORD_FILE_ID": 42,
                    "CRM_ENTITY_TYPE": "CONTACT", "CRM_ENTITY_ID": "11",
                    "PORTAL_USER_ID": "5",
                    "CALL_RECORD_URL": (
                        "https://microchops.bitrix24.by/rest/download.json?token=FRESH_CALL"
                    ),
                }]})
            return super().post(url, json=json, timeout=timeout,
                                allow_redirects=allow_redirects)

    binaries = (tmp_path / "binaries").resolve()
    module.export_binaries(WEBHOOK, metadata, binaries, session=SameCallIdentity())
    return bitrix_root, onec_root, binaries


def _read_binary_dataset(root, name):
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((root / name).glob("*.json"))
    ]


def _replace_binary_dataset(root, name, rows):
    folder = root / name
    for path in folder.iterdir():
        path.unlink()
    folder.rmdir()
    dataset = module.Dataset(root, name)
    for index, row in enumerate(rows):
        dataset.add(str(index), row)
    return dataset.summary()


def _rewrite_binary_snapshot(root, *, links=None, inventory=None):
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if links is not None:
        manifest["binary_links"] = _replace_binary_dataset(root, "binary_links", links)
    if inventory is not None:
        manifest["binary_inventory"] = _replace_binary_dataset(
            root, "binary_inventory", inventory
        )
    inventory_rows = _read_binary_dataset(root, "binary_inventory")
    retained = {row["filename"] for row in inventory_rows}
    files = root / "binary_files"
    for path in files.iterdir():
        if path.name not in retained:
            path.unlink()
    fingerprint = module.hashlib.sha256()
    total_bytes = 0
    actual_files = sorted(files.iterdir(), key=lambda path: path.name)
    for path in actual_files:
        body = path.read_bytes()
        digest = module.hashlib.sha256(body).hexdigest()
        total_bytes += len(body)
        fingerprint.update(f"{path.name}:{len(body)}:{digest}\n".encode("ascii"))
    manifest["binary_files"] = {
        "records": len(actual_files), "bytes": total_bytes,
        "sha256": fingerprint.hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_private_stage_seals_call_binary_as_blocked_v3_without_signed_urls(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root, binaries = _call_binary_stage_inputs(tmp_path)
    output = tmp_path / "cache"

    summary = module.stage_import_cache(bitrix_root, onec_root, output, binaries)

    assert summary["format"] == "CRM-LIVE-001-private-cache-v3"
    assert summary["ready_for_load"] is False
    assert summary["blocked_source_groups"]["call_recordings"] == 1
    assert summary["call_binary_files"]["records"] == 1
    links = [json.loads(line) for line in (output / "bx_call_binary_links.jsonl")
             .read_text(encoding="utf-8").splitlines()]
    assert links == [{
        "source": "call", "source_id": "10", "call_id": "call-10",
        "record_file_id": "42",
        "entity_type": "CONTACT", "entity_id": "11", "portal_user_id": "5",
        "binary_key": "call:10",
    }]
    inventory = [json.loads(line) for line in (output / "bx_call_binary_inventory.jsonl")
                 .read_text(encoding="utf-8").splitlines()]
    assert len(inventory) == 1
    assert inventory[0]["key"] == links[0]["binary_key"]
    copied = output / "call_binary_files" / inventory[0]["filename"]
    assert copied.read_bytes() == b"DATA"
    call_rows = [json.loads(line) for line in (output / "bx_calls.jsonl")
                 .read_text(encoding="utf-8").splitlines()]
    assert "CALL_RECORD_URL" not in call_rows[0]
    sealed_text = "".join(
        path.read_text(encoding="utf-8")
        for path in [
            output / "bx_calls.jsonl", output / "bx_call_binary_links.jsonl",
            output / "bx_call_binary_inventory.jsonl", output / "private-source-manifest.json",
        ]
    )
    assert "SOURCE_SIGNED_TOKEN" not in sealed_text
    assert "FRESH_CALL" not in sealed_text
    from scripts import import_month
    with pytest.raises(RuntimeError, match="^BITRIX_CALL_RECORDINGS_UNSUPPORTED$"):
        import_month._verify_private_cache(output)

    # A correctly sealed marker cannot make an unsupported V3 cache loadable.
    manifest_path = output / "private-source-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["ready_for_load"] = True
    body = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    manifest_path.write_bytes(body)
    (output / "PRIVATE_CACHE_FORMAT").write_text(
        manifest["format"] + ":" + module.hashlib.sha256(body).hexdigest() + "\n", encoding="ascii",
    )
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_NOT_LOADABLE"):
        import_month._verify_private_cache(output)


def test_private_stage_rejects_missing_call_binary_link(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root, binaries = _call_binary_stage_inputs(tmp_path)
    _rewrite_binary_snapshot(binaries, links=[], inventory=[])

    with pytest.raises(module.ExportError, match="BINARY_CALL_LINK_MISMATCH"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache", binaries)


def test_private_stage_rejects_unlinked_call_binary_inventory(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root, binaries = _call_binary_stage_inputs(tmp_path)
    _rewrite_binary_snapshot(binaries, links=[])

    with pytest.raises(module.ExportError, match="UNLINKED_BINARY_INVENTORY"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache", binaries)


@pytest.mark.parametrize(("field", "changed"), [
    ("ID", "11"), ("CALL_ID", "call-drift"),
    ("RECORD_FILE_ID", "43"),
    ("CRM_ENTITY_TYPE", "DEAL"), ("CRM_ENTITY_ID", "12"),
    ("PORTAL_USER_ID", "6"),
])
def test_private_stage_rejects_call_source_identity_drift(tmp_path, field, changed):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root, binaries = _call_binary_stage_inputs(
        tmp_path, source_call_overrides={field: changed}
    )

    with pytest.raises(module.ExportError, match="BINARY_CALL_LINK_MISMATCH"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache", binaries)


@pytest.mark.parametrize("link_change", [
    {"source": "task"},
    {"download_url": "https://microchops.bitrix24.by/file?token=UNSUPPORTED"},
])
def test_private_stage_rejects_unsupported_call_binary_link_sidecars(tmp_path, link_change):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root, binaries = _call_binary_stage_inputs(tmp_path)
    links = _read_binary_dataset(binaries, "binary_links")
    links[0] = {**links[0], **link_change}
    _rewrite_binary_snapshot(binaries, links=links)

    error = "UNSUPPORTED_BINARY_SOURCE" if link_change.get("source") == "task" \
        else "BINARY_CALL_LINK_MISMATCH"
    with pytest.raises(module.ExportError, match=error):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache", binaries)


def test_private_stage_rejects_duplicate_call_binary_links(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root, binaries = _call_binary_stage_inputs(tmp_path)
    links = _read_binary_dataset(binaries, "binary_links")
    links.append(dict(links[0]))
    _rewrite_binary_snapshot(binaries, links=links)

    with pytest.raises(module.ExportError, match="BINARY_CALL_LINK_MISMATCH"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache", binaries)


def test_private_stage_rejects_call_inventory_url_sidecar(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root, binaries = _call_binary_stage_inputs(tmp_path)
    inventory = _read_binary_dataset(binaries, "binary_inventory")
    inventory[0]["download_url"] = (
        "https://microchops.bitrix24.by/file?token=UNSUPPORTED"
    )
    _rewrite_binary_snapshot(binaries, inventory=inventory)

    with pytest.raises(module.ExportError, match="BINARY_CALL_INVENTORY_MISMATCH"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache", binaries)


def test_private_stage_rejects_url_in_comment_link_for_v3_cache(tmp_path):
    tmp_path = tmp_path.resolve()
    comments = [{
        "ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "11",
        "FILES": {"3": {"id": 3}},
    }]
    bitrix_root, onec_root, binaries = _call_binary_stage_inputs(
        tmp_path, comments=comments
    )
    links = _read_binary_dataset(binaries, "binary_links")
    comment = next(row for row in links if row["source"] == "comment")
    comment["download_url"] = "https://microchops.bitrix24.by/file?token=UNSUPPORTED"
    _rewrite_binary_snapshot(binaries, links=links)

    with pytest.raises(module.ExportError, match="BINARY_COMMENT_LINK_MISMATCH"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache", binaries)


def test_private_stage_rejects_url_in_comment_inventory_for_v3_cache(tmp_path):
    tmp_path = tmp_path.resolve()
    comments = [{
        "ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "11",
        "FILES": {"3": {"id": 3}},
    }]
    bitrix_root, onec_root, binaries = _call_binary_stage_inputs(
        tmp_path, comments=comments
    )
    inventory = _read_binary_dataset(binaries, "binary_inventory")
    comment = next(row for row in inventory if row["key"] == "disk:3")
    comment["CALL_RECORD_URL"] = CALL_RECORD_URL
    _rewrite_binary_snapshot(binaries, inventory=inventory)

    with pytest.raises(module.ExportError, match="BINARY_COMMENT_INVENTORY_MISMATCH"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache", binaries)


@pytest.mark.parametrize(("field", "error"), [
    ("CALL_RECORD_URL", "BAD_CALL_RECORD_URL"),
    ("RECORD_FILE_ID", "BAD_CALL_FILE_ID"),
])
@pytest.mark.parametrize("bad", [False, 0, [], {}])
def test_private_stage_rejects_falsy_invalid_call_recording_fields(
    tmp_path, field, error, bad
):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root, with_products=False,
                           calls=[{"ID": "10", field: bad}])
    output = tmp_path / "cache"
    with pytest.raises(module.ExportError, match=error):
        module.stage_import_cache(bitrix_root, onec_root, output)
    assert not (output / "private-source-manifest.json").exists()


@pytest.mark.parametrize("changed_id", ["010", "11"])
def test_private_stage_rejects_resealed_call_id_unbound_from_source_filename(
    tmp_path, changed_id
):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root, binaries = _call_binary_stage_inputs(tmp_path)
    row = next(module._staged_rows(bitrix_root, "calls"))
    row["ID"] = changed_id
    raw = json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")
    _replace_private_source_row_bytes(bitrix_root, "calls", raw)
    with pytest.raises(module.ExportError, match="BAD_PRIVATE_SOURCE_ID"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache", binaries)


def test_private_stage_seals_product_evidence_and_allows_supported_rows(tmp_path, capsys):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root)
    output = tmp_path / "cache"
    summary = module.stage_import_cache(bitrix_root, onec_root, output)
    assert len(summary["cache"]) == 14
    assert summary["ready_for_load"] is True
    assert summary["blocked_source_groups"] == {}
    assert (output / "bx_deals.jsonl").read_text(encoding="utf-8").count("\n") == 1
    assert json.loads((output / "bx_product_rows.jsonl").read_text(encoding="utf-8"))["rows"][0]["ID"] == "9"
    assert json.loads((output / "bx_products.jsonl").read_text(encoding="utf-8"))["XML_ID"] == "ref-1"
    assert (output / "bx_stage_history.jsonl").read_text(encoding="utf-8").count("\n") == 1
    assert (output / "bx_timeline_comments.jsonl").read_text(encoding="utf-8").count("\n") == 1
    assert (output / "bx_tasks.jsonl").read_bytes() == b""
    assert summary["cache"]["bx_tasks"]["records"] == 0
    assert not (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    assert (output / "PRIVATE_CACHE_FORMAT").read_text(encoding="ascii").startswith(
        "CRM-LIVE-001-private-cache-v1:")
    manifest = (output / "private-source-manifest.json").read_text(encoding="utf-8")
    assert "PRIVATE_SOURCE" not in manifest + capsys.readouterr().out
    assert "PRIVATE_1C" not in manifest
    assert "PRIVATE_PRODUCT" not in manifest
    assert "PRIVATE_ROW_NAME" not in manifest
    assert "PRIVATE_COMMENT" not in manifest
    from scripts import import_month
    assert import_month._verify_private_cache(output) is not None


def test_private_stage_empty_product_groups_keep_complete_sealed_format(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root, with_products=False)
    output = tmp_path / "cache"
    summary = module.stage_import_cache(bitrix_root, onec_root, output)
    assert summary["ready_for_load"] is True
    assert summary["blocked_source_groups"] == {}
    empty_row_envelopes = [
        json.loads(line) for line in (output / "bx_product_rows.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert empty_row_envelopes == [{"deal_id": "1", "rows": []}]
    from scripts import import_month
    assert import_month._verify_private_cache(output) is not None


@pytest.mark.parametrize(
    "envelopes,catalog_rows,error_code",
    [
        ([{"deal_id": "2", "rows": [{"ID": "9", "PRODUCT_ID": "7"}]}],
         [{"ID": "7", "XML_ID": "ref-1", "CODE": "SKU-1", "NAME": "P"}],
         "BAD_PRODUCT_ROW_LINK"),
        ([{"deal_id": "1", "rows": [
            {"ID": "9", "PRODUCT_ID": "7"}, {"ID": "9", "PRODUCT_ID": "7"},
        ]}],
         [{"ID": "7", "XML_ID": "ref-1", "CODE": "SKU-1", "NAME": "P"}],
         "BAD_PRODUCT_ROW_LINK"),
        ([{"deal_id": "1", "rows": [{"PRODUCT_ID": "7"}]}],
         [{"ID": "7", "XML_ID": "ref-1", "CODE": "SKU-1", "NAME": "P"}],
         "BAD_PRODUCT_ROW_LINK"),
        ([{"deal_id": "1", "rows": [{"ID": "9", "PRODUCT_ID": "0"}]}],
         [], "BAD_PRODUCT_ROW_LINK"),
        ([{"deal_id": "1", "rows": [{"ID": "9", "PRODUCT_ID": "7"}]}],
         [], "PRODUCT_CATALOG_EVIDENCE_MISMATCH"),
        ([{"deal_id": "1", "rows": [{"ID": "9", "PRODUCT_ID": "7"}]}],
         [{"ID": "8", "XML_ID": "ref-1", "CODE": "SKU-1", "NAME": "P"}],
         "PRODUCT_CATALOG_EVIDENCE_MISMATCH"),
        ([{"deal_id": "1", "rows": [{"ID": "9", "PRODUCT_ID": "7"}]}],
         [{"ID": "7", "XML_ID": "ref-1", "CODE": "SKU-1", "NAME": "P"},
          {"ID": "8", "XML_ID": "ref-2", "CODE": "SKU-2", "NAME": "ORPHAN"}],
         "PRODUCT_CATALOG_EVIDENCE_MISMATCH"),
        ([{"deal_id": "1", "rows": [{
            "ID": "9", "PRODUCT_ID": "7", "OWNER_ID": "2", "OWNER_TYPE": "D",
        }]}],
         [{"ID": "7", "XML_ID": "ref-1", "CODE": "SKU-1", "NAME": "P"}],
         "BAD_PRODUCT_ROW_LINK"),
    ],
)
def test_private_stage_rejects_unresolved_or_uncertain_product_rows(
    tmp_path, envelopes, catalog_rows, error_code
):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(
        bitrix_root, onec_root,
        product_envelopes=envelopes, catalog_rows=catalog_rows,
    )
    output = tmp_path / "cache"

    with pytest.raises(module.ExportError, match=error_code):
        module.stage_import_cache(bitrix_root, onec_root, output)

    assert (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    assert not (output / "private-source-manifest.json").exists()


def test_private_stage_rejects_product_row_source_key_alias(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root)
    _replace_private_source_row_bytes(
        bitrix_root, "deal_product_rows",
        b'{"deal_id":"01","rows":[{"ID":"9","PRODUCT_ID":"7"}]}',
    )
    output = tmp_path / "cache"

    with pytest.raises(module.ExportError, match="BAD_PRIVATE_SOURCE_ID"):
        module.stage_import_cache(bitrix_root, onec_root, output)

    assert (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    assert not (output / "private-source-manifest.json").exists()


def test_private_stage_rejects_duplicate_raw_product_row_json_key(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root)
    _replace_private_source_row_bytes(
        bitrix_root, "deal_product_rows",
        b'{"deal_id":"1","deal_id":"2","rows":[{"ID":"9","PRODUCT_ID":"7"}]}',
    )
    output = tmp_path / "cache"

    with pytest.raises(module.ExportError, match="BAD_STAGED_DATASET"):
        module.stage_import_cache(bitrix_root, onec_root, output)

    assert (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    assert not (output / "private-source-manifest.json").exists()


def test_private_stage_rejects_incomplete_duplicate_or_non_ascii_product_identity(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(
        bitrix_root, onec_root, with_products=False,
        deal_rows=[
            {"ID": "1", "TITLE": "PRIVATE_SOURCE"},
            {"ID": "2", "TITLE": "PRIVATE_SOURCE_2"},
        ],
        product_envelopes=[{"deal_id": "1", "rows": []}],
        catalog_rows=[],
    )
    with pytest.raises(module.ExportError, match="BAD_PRODUCT_ROW_LINK"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache-missing")

    bitrix_root, onec_root = tmp_path / "bitrix-dup", tmp_path / "onec-dup"
    _private_stage_sources(
        bitrix_root, onec_root,
        deal_rows=[
            {"ID": "1", "TITLE": "PRIVATE_SOURCE"},
            {"ID": "2", "TITLE": "PRIVATE_SOURCE_2"},
        ],
        product_envelopes=[
            {"deal_id": "1", "rows": [{"ID": "9", "PRODUCT_ID": "7"}]},
            {"deal_id": "2", "rows": [{"ID": "9", "PRODUCT_ID": "8"}]},
        ],
        catalog_rows=[
            {"ID": "7", "XML_ID": "ref-1", "CODE": "SKU-1", "NAME": "P1"},
            {"ID": "8", "XML_ID": "ref-2", "CODE": "SKU-2", "NAME": "P2"},
        ],
    )
    with pytest.raises(module.ExportError, match="BAD_PRODUCT_ROW_LINK"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache-dup")

    bitrix_root, onec_root = tmp_path / "bitrix-digit", tmp_path / "onec-digit"
    _private_stage_sources(
        bitrix_root, onec_root,
        product_envelopes=[{"deal_id": "1", "rows": [{"ID": "٩", "PRODUCT_ID": "7"}]}],
        catalog_rows=[{"ID": "7", "XML_ID": "ref-1", "CODE": "SKU-1", "NAME": "P"}],
    )
    with pytest.raises(module.ExportError, match="BAD_PRODUCT_ROW_LINK"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache-digit")


def test_private_stage_rejects_swapped_catalog_file_contents(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(
        bitrix_root, onec_root,
        product_envelopes=[{"deal_id": "1", "rows": [
            {"ID": "9", "PRODUCT_ID": "7"}, {"ID": "10", "PRODUCT_ID": "8"},
        ]}],
        catalog_rows=[
            {"ID": "7", "XML_ID": "ref-1", "CODE": "SKU-1", "NAME": "P1"},
            {"ID": "8", "XML_ID": "ref-2", "CODE": "SKU-2", "NAME": "P2"},
        ],
    )
    folder = bitrix_root / "product_catalog_evidence"
    files = sorted(folder.glob("*.json"))
    first, second = files[0].read_bytes(), files[1].read_bytes()
    files[0].write_bytes(second)
    files[1].write_bytes(first)
    fingerprint = module.hashlib.sha256()
    total = 0
    for path in sorted(folder.glob("*.json")):
        body = path.read_bytes()
        digest = module.hashlib.sha256(body).hexdigest()
        fingerprint.update(f"{path.name}:{len(body)}:{digest}\n".encode("ascii"))
        total += len(body)
    manifest_path = bitrix_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["product_catalog_evidence"] = {
        "records": 2, "bytes": total, "sha256": fingerprint.hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(module.ExportError, match="BAD_PRIVATE_SOURCE_ID"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache")


def test_private_stage_counts_nested_product_rows_not_deal_envelopes(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(
        bitrix_root, onec_root,
        product_envelopes=[{"deal_id": "1", "rows": [
            {"ID": "9", "PRODUCT_ID": "7"}, {"ID": "10", "PRODUCT_ID": "8"},
        ]}],
        catalog_rows=[
            {"ID": "7", "XML_ID": "ref-1", "CODE": "SKU-1", "NAME": "P1"},
            {"ID": "8", "XML_ID": "ref-2", "CODE": "SKU-2", "NAME": "P2"},
        ],
    )
    output = tmp_path / "cache"

    summary = module.stage_import_cache(bitrix_root, onec_root, output)

    assert summary["blocked_source_groups"] == {}
    assert summary["ready_for_load"] is True
    assert summary["cache"]["bx_product_rows"]["records"] == 1


def test_private_stage_preserves_comment_owner_identity_and_blocks_attachments(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    comments = [
        {"ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "1", "FILES": {}},
        {"ID": "7", "ENTITY_TYPE": "lead", "ENTITY_ID": "1",
         "FILES": {"3": {"id": 3}}},
    ]
    _private_stage_sources(bitrix_root, onec_root, with_products=False, comments=comments)
    output = tmp_path / "cache"
    summary = module.stage_import_cache(bitrix_root, onec_root, output)
    assert summary["cache"]["bx_timeline_comments"]["records"] == 2
    assert summary["blocked_source_groups"] == {"timeline_attachments": 1}
    assert summary["ready_for_load"] is False
    from scripts import import_month

    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_NOT_LOADABLE"):
        import_month._verify_private_cache(output)


def test_private_stage_seals_deal_comment_binary_subset_with_empty_tasks(tmp_path, capsys):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    comments = [{"ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "1",
                 "FILES": {"3": {"id": 3, "name": "PRIVATE_NAME"}}}]
    _private_stage_sources(bitrix_root, onec_root, with_products=False, comments=comments)
    metadata = tmp_path / "binary_metadata"
    _binary_metadata(
        metadata, comments=comments, deals=[{"ID": "1"}], tasks=[], call_url=None
    )
    binaries = (tmp_path / "binaries").resolve()
    module.export_binaries(WEBHOOK, metadata, binaries, session=BinarySession())

    output = tmp_path / "cache"
    summary = module.stage_import_cache(bitrix_root, onec_root, output, binaries)
    assert summary["format"] == "CRM-LIVE-001-private-cache-v2"
    assert summary["ready_for_load"] is True
    assert summary["blocked_source_groups"] == {}
    assert len(summary["cache"]) == 16
    assert summary["cache"]["bx_comment_binary_links"]["records"] == 1
    assert summary["cache"]["bx_comment_binary_inventory"]["records"] == 1
    assert summary["comment_binary_files"]["records"] == 1
    assert [path.read_bytes() for path in (output / "comment_binary_files").iterdir()] == [b"DATA"]
    assert (output / "PRIVATE_CACHE_FORMAT").read_text(encoding="ascii").startswith(
        "CRM-LIVE-001-private-cache-v2:"
    )
    manifest = (output / "private-source-manifest.json").read_text(encoding="utf-8")
    assert "PRIVATE_NAME" not in manifest + capsys.readouterr().out
    from scripts import import_month
    assert import_month._verify_private_cache(output) is not None


def test_private_stage_preserves_full_unique_task_payload_in_sealed_cache(tmp_path, capsys):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    task = {
        "id": "41",
        "title": "PRIVATE_TASK_TITLE",
        "description": "x" * 700,
        "ufCrmTask": ["D_30", "L_80"],
        "ufTaskWebdavFiles": [],
        "unknownSourceField": {"kept": ["raw", 17]},
    }
    _private_stage_sources(bitrix_root, onec_root, with_products=False, tasks=[task])
    output = tmp_path / "cache"

    summary = module.stage_import_cache(bitrix_root, onec_root, output)

    task_bytes = (output / "bx_tasks.jsonl").read_bytes()
    task_lines = task_bytes.splitlines()
    manifest_body = (output / "private-source-manifest.json").read_bytes()
    manifest = json.loads(manifest_body)
    marker = (output / "PRIVATE_CACHE_FORMAT").read_text(encoding="ascii")
    expected_marker = (
        "CRM-LIVE-001-private-cache-v1:" + module.hashlib.sha256(manifest_body).hexdigest() + "\n"
    )
    assert len(task_lines) == 1
    assert json.loads(task_lines[0]) == task
    assert summary["cache"]["bx_tasks"]["records"] == 1
    assert summary["cache"]["bx_tasks"]["bytes"] == len(task_bytes)
    assert summary["cache"]["bx_tasks"]["sha256"] == module.hashlib.sha256(task_bytes).hexdigest()
    assert manifest == summary
    assert marker == expected_marker
    assert summary["ready_for_load"] is True
    assert summary["blocked_source_groups"] == {}
    assert not (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    assert "PRIVATE_TASK_TITLE" not in manifest_body.decode("utf-8") + capsys.readouterr().out
    from scripts import import_month
    assert import_month._verify_private_cache(output) is not None


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("ufTaskWebdavFiles", ["n77"], "task_attachments_unimported"),
        ("ufMailMessage", {"id": "901"}, "task_mail_unimported"),
    ],
)
def test_private_stage_blocks_unsupported_task_sidecars(
    tmp_path, field, value, blocker
):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(
        bitrix_root, onec_root, with_products=False,
        tasks=[{"id": "41", "title": "PRIVATE_TASK_TITLE", field: value}],
    )
    output = tmp_path / "cache"

    summary = module.stage_import_cache(bitrix_root, onec_root, output)

    assert summary["ready_for_load"] is False
    assert summary["blocked_source_groups"] == {blocker: 1}
    assert not (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    from scripts import import_month
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_NOT_LOADABLE"):
        import_month._verify_private_cache(output)


@pytest.mark.parametrize("tasks,task_keys", [
    ([{"id": "41"}, {"ID": "41"}], ["row-a", "row-b"]),
    ([{"title": "PRIVATE_MISSING_ID"}], ["row-a"]),
    ([{"id": "41", "ID": "42"}], ["row-a"]),
])
def test_private_stage_rejects_duplicate_missing_or_conflicting_task_identity(
    tmp_path, tasks, task_keys
):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(
        bitrix_root, onec_root, tasks=tasks, task_keys=task_keys,
    )
    output = tmp_path / "cache"

    with pytest.raises(module.ExportError, match="BAD_PRIVATE_SOURCE_ID"):
        module.stage_import_cache(bitrix_root, onec_root, output)

    assert (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    assert not (output / "private-source-manifest.json").exists()


def _replace_private_source_row_bytes(root, dataset_name, raw):
    path = next((root / dataset_name).glob("*.json"))
    path.write_bytes(raw)
    digest = module.hashlib.sha256(raw).hexdigest()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest[dataset_name] = {
        "records": 1,
        "bytes": len(raw),
        "sha256": module.hashlib.sha256(
            f"{path.name}:{len(raw)}:{digest}\n".encode("ascii")
        ).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_private_stage_rejects_duplicate_raw_task_key_with_matching_digest(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root, tasks=[{"id": "41"}])
    _replace_private_source_row_bytes(
        bitrix_root, "tasks", b'{"id":"41","id":"42","title":"PRIVATE_TASK"}'
    )
    output = tmp_path / "cache"
    with pytest.raises(module.ExportError, match="BAD_STAGED_DATASET"):
        module.stage_import_cache(bitrix_root, onec_root, output)
    assert (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    assert not (output / "private-source-manifest.json").exists()


def test_private_stage_rejects_duplicate_raw_source_manifest_key(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root)
    manifest_path = bitrix_root / "manifest.json"
    raw = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        raw.replace('"tasks":', '"tasks":{"records":999},"tasks":', 1),
        encoding="utf-8",
    )
    with pytest.raises(module.ExportError, match="BAD_PRIVATE_SOURCE_MANIFEST"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache")


def _private_stage_binary_sources(tmp_path):
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    comments = [{
        "ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "1",
        "FILES": {"3": {"id": 3}},
    }]
    _private_stage_sources(bitrix_root, onec_root, comments=comments)
    metadata = tmp_path / "binary_metadata"
    _binary_metadata(metadata, comments=comments, deals=[{"ID": "1"}], tasks=[], call_url=None)
    binaries = (tmp_path / "binaries").resolve()
    module.export_binaries(WEBHOOK, metadata, binaries, session=BinarySession())
    return bitrix_root, onec_root, binaries


def test_private_stage_rejects_duplicate_raw_binary_link_source(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root, binaries = _private_stage_binary_sources(tmp_path)
    path = next((binaries / "binary_links").glob("*.json"))
    raw = path.read_bytes().replace(
        b'"source":"comment"', b'"source":"task","source":"comment"', 1
    )
    assert b'"source":"task","source":"comment"' in raw
    _replace_private_source_row_bytes(binaries, "binary_links", raw)
    output = tmp_path / "cache"
    with pytest.raises(module.ExportError, match="BAD_STAGED_DATASET"):
        module.stage_import_cache(bitrix_root, onec_root, output, binaries)
    assert (output / "PRIVATE_CACHE_INCOMPLETE").exists()


def test_private_stage_rejects_duplicate_raw_binary_manifest_key(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root, binaries = _private_stage_binary_sources(tmp_path)
    manifest_path = binaries / "manifest.json"
    raw = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        raw.replace('"binary_links":', '"binary_links":{"records":999},"binary_links":', 1),
        encoding="utf-8",
    )
    output = tmp_path / "cache"
    with pytest.raises(module.ExportError, match="BAD_BINARY_SNAPSHOT"):
        module.stage_import_cache(bitrix_root, onec_root, output, binaries)
    assert (output / "PRIVATE_CACHE_INCOMPLETE").exists()


@pytest.mark.parametrize("unsupported_source", ["task", "crm_file", "unknown"])
def test_private_stage_rejects_sidecar_only_unsupported_binary_sources(
    tmp_path, unsupported_source
):
    tmp_path = tmp_path.resolve()
    comments = [{
        "ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "1",
        "FILES": {"3": {"id": 3}},
    }]
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root, comments=comments)
    metadata = tmp_path / "binary_metadata"
    _binary_metadata(
        metadata, comments=comments, deals=[{"ID": "1"}], tasks=[], call_url=None
    )
    binaries = (tmp_path / "binaries").resolve()
    module.export_binaries(WEBHOOK, metadata, binaries, session=BinarySession())

    source_links = list(module._staged_rows(binaries, "binary_links"))
    binary_links_dir = binaries / "binary_links"
    for path in binary_links_dir.iterdir():
        path.unlink()
    binary_links_dir.rmdir()
    sidecar_links = module.Dataset(binaries, "binary_links")
    for index, row in enumerate(source_links):
        sidecar_links.add(str(index), row)
    sidecar_links.add("unmapped", {
        "source": unsupported_source,
        "source_id": "8",
        "binary_key": "disk:3",
    })
    manifest_path = binaries / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["binary_links"] = sidecar_links.summary()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    output = tmp_path / "cache"
    with pytest.raises(module.ExportError, match="UNSUPPORTED_BINARY_SOURCE") as exc:
        module.stage_import_cache(bitrix_root, onec_root, output, binaries)
    assert unsupported_source not in str(exc.value)
    assert (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    assert not (output / "private-source-manifest.json").exists()


def test_private_stage_rejects_unavailable_recordings(tmp_path):
    tmp_path = tmp_path.resolve()
    comments = [{
        "ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "1",
        "FILES": {"3": {"id": 3}},
    }]
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root, comments=comments)
    metadata = tmp_path / "binary_metadata"
    _binary_metadata(
        metadata, comments=comments, deals=[{"ID": "1"}], tasks=[], call_url=None
    )
    binaries = (tmp_path / "binaries").resolve()
    module.export_binaries(WEBHOOK, metadata, binaries, session=BinarySession())
    manifest_path = binaries / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["unavailable_recordings"]["records"] = 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    output = tmp_path / "cache"
    with pytest.raises(module.ExportError, match="BINARY_RECORDINGS_UNAVAILABLE"):
        module.stage_import_cache(bitrix_root, onec_root, output, binaries)
    assert (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    assert not (output / "private-source-manifest.json").exists()


def test_private_stage_rejects_unlinked_binary_inventory(tmp_path):
    tmp_path = tmp_path.resolve()
    comments = [{
        "ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "1",
        "FILES": {"3": {"id": 3}},
    }]
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root, comments=comments)
    metadata = tmp_path / "binary_metadata"
    _binary_metadata(
        metadata, comments=comments, deals=[{"ID": "1"}], tasks=[], call_url=None
    )
    binaries = (tmp_path / "binaries").resolve()
    module.export_binaries(WEBHOOK, metadata, binaries, session=BinarySession())

    inventory_rows = list(module._staged_rows(binaries, "binary_inventory"))
    inventory_dir = binaries / "binary_inventory"
    for path in inventory_dir.iterdir():
        path.unlink()
    inventory_dir.rmdir()
    inventory = module.Dataset(binaries, "binary_inventory")
    for row in inventory_rows:
        inventory.add(row["key"], row)

    orphan_key = "disk:902"
    orphan_body = b"ORPHAN"
    orphan_digest = module.hashlib.sha256(orphan_body).hexdigest()
    orphan_filename = module.hashlib.sha256(orphan_key.encode("ascii")).hexdigest() + ".bin"
    (binaries / "binary_files" / orphan_filename).write_bytes(orphan_body)
    inventory.add(orphan_key, {
        "key": orphan_key,
        "filename": orphan_filename,
        "bytes": len(orphan_body),
        "sha256": orphan_digest,
        "content_type": "application/octet-stream",
        "name": "orphan.bin",
    })

    manifest_path = binaries / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["binary_inventory"] = inventory.summary()
    file_fingerprint = module.hashlib.sha256()
    total_bytes = 0
    files = sorted((binaries / "binary_files").iterdir(), key=lambda path: path.name)
    for path in files:
        body = path.read_bytes()
        digest = module.hashlib.sha256(body).hexdigest()
        total_bytes += len(body)
        file_fingerprint.update(f"{path.name}:{len(body)}:{digest}\n".encode("ascii"))
    manifest["binary_files"] = {
        "records": len(files), "bytes": total_bytes, "sha256": file_fingerprint.hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    output = tmp_path / "cache"
    with pytest.raises(module.ExportError, match="UNLINKED_BINARY_INVENTORY"):
        module.stage_import_cache(bitrix_root, onec_root, output, binaries)
    assert (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    assert not (output / "private-source-manifest.json").exists()


def test_private_stage_rejects_comment_binary_owner_mismatch(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root, comments=[
        {"ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "1",
         "FILES": {"3": {"id": 3}}},
    ])
    metadata = tmp_path / "binary_metadata"
    _binary_metadata(metadata, tasks=[], call_url=None)  # file belongs to deal 11, not deal 1
    binaries = (tmp_path / "binaries").resolve()
    module.export_binaries(WEBHOOK, metadata, binaries, session=BinarySession())
    output = tmp_path / "cache"
    with pytest.raises(module.ExportError, match="BINARY_COMMENT_LINK_MISMATCH"):
        module.stage_import_cache(bitrix_root, onec_root, output, binaries)
    assert (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    assert not (output / "private-source-manifest.json").exists()


def test_private_stage_rechecks_metadata_manifest_after_binary_phase(tmp_path, monkeypatch):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    comment7 = {"ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "1",
                "FILES": {"3": {"id": 3}}}
    comment8 = {**comment7, "ID": "8"}
    _private_stage_sources(bitrix_root, onec_root, comments=[comment7])
    metadata = tmp_path / "binary_metadata"
    _binary_metadata(
        metadata, comments=[comment8], deals=[{"ID": "1"}], tasks=[], call_url=None
    )
    binaries = (tmp_path / "binaries").resolve()
    module.export_binaries(WEBHOOK, metadata, binaries, session=BinarySession())
    original = module._stage_supported_binary_cache

    def source_changes_after_metadata_staging(bitrix, binary, output):
        path = next((bitrix / "timeline_comments").glob("*.json"))
        body = json.dumps(comment8, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
        path.write_bytes(body)
        manifest_path = bitrix / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        digest = module.hashlib.sha256(body).hexdigest()
        fingerprint = module.hashlib.sha256(
            f"{path.name}:{len(body)}:{digest}\n".encode("ascii")
        ).hexdigest()
        manifest["timeline_comments"] = {"records": 1, "bytes": len(body),
                                         "sha256": fingerprint}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return original(bitrix, binary, output)

    monkeypatch.setattr(module, "_stage_supported_binary_cache",
                        source_changes_after_metadata_staging)
    output = tmp_path / "cache"
    with pytest.raises(module.ExportError, match="PRIVATE_SOURCE_CHANGED"):
        module.stage_import_cache(bitrix_root, onec_root, output, binaries)
    assert (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    assert not (output / "private-source-manifest.json").exists()


def test_private_stage_rejects_duplicate_comment_source_key(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    comments = [
        {"ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "1", "FILES": {}},
        {"ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "1", "FILES": {}},
    ]
    # Two valid dataset keys can still carry the same source identity.
    _private_stage_sources(bitrix_root, onec_root, comments=comments)
    with pytest.raises(module.ExportError, match="BAD_PRIVATE_SOURCE_ID"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache")


def test_private_stage_rejects_comment_files_wrong_shape(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root, comments=[{
        "ID": "7", "ENTITY_TYPE": "deal", "ENTITY_ID": "1", "FILES": [],
    }])
    with pytest.raises(module.ExportError, match="BAD_COMMENT_FILES"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache")


def test_private_stage_rejects_tampered_source_without_loadable_cache(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root)
    source = next((bitrix_root / "deals").glob("*.json"))
    source.write_text('{"ID":"1","TITLE":"changed"}', encoding="utf-8")
    output = tmp_path / "cache"
    with pytest.raises(module.ExportError, match="STAGED_DATASET_MISMATCH"):
        module.stage_import_cache(bitrix_root, onec_root, output)
    assert (output / "PRIVATE_CACHE_INCOMPLETE").exists()
    assert not (output / "private-source-manifest.json").exists()


def test_private_stage_rejects_missing_empty_dataset_folder(tmp_path):
    tmp_path = tmp_path.resolve()
    bitrix_root, onec_root = tmp_path / "bitrix", tmp_path / "onec"
    _private_stage_sources(bitrix_root, onec_root)
    (bitrix_root / "field_schemas").rmdir()
    with pytest.raises(module.ExportError, match="BAD_STAGED_DATASET"):
        module.stage_import_cache(bitrix_root, onec_root, tmp_path / "cache")


def test_binary_phase_rejects_tampered_metadata_before_download(tmp_path):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata)
    path = next((metadata / "tasks").glob("*.json"))
    path.write_text('{"id":"999"}', encoding="utf-8")
    session = BinarySession()
    with pytest.raises(module.ExportError, match="STAGED_DATASET_MISMATCH"):
        module.export_binaries(WEBHOOK, metadata, tmp_path / "binaries", session=session)
    assert session.downloads == []


@pytest.mark.parametrize("response,code", [
    (BinaryResponse(b"DATA", content_type="text/html"), "BINARY_NOT_FILE"),
    (BinaryResponse(b"<html>LOGIN</html>", content_type="text/plain"), "BINARY_NOT_FILE"),
    (BinaryResponse(b"BAD", length=4), "BINARY_SIZE_MISMATCH"),
])
def test_binary_phase_rejects_html_or_incomplete_file_without_leaking(tmp_path, response, code):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata)
    session = BinarySession(response=response)
    output = tmp_path / "binaries"
    with pytest.raises(module.ExportError, match=code) as exc:
        module.export_binaries(WEBHOOK, metadata, output, session=session)
    assert "PRIVATE" not in str(exc.value)
    assert not list((output / "binary_files").glob("*.bin"))
    assert not (output / "manifest.json").exists()


def test_binary_phase_blocks_external_signed_url(tmp_path):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata, call_url="https://elsewhere.example/rest/download.json?token=PRIVATE")
    session = BinarySession()
    with pytest.raises(module.ExportError, match="BAD_DOWNLOAD_URL"):
        module.export_binaries(WEBHOOK, metadata, tmp_path / "binaries", session=session)
    assert session.downloads == []


def test_binary_phase_blocks_portal_api_url_even_on_same_host():
    with pytest.raises(module.ExportError, match="BAD_DOWNLOAD_URL"):
        module._signed_download_url("https://microchops.bitrix24.by/rest/1/KEY/crm.deal.add.json?x=1")


def test_crm_file_field_uses_universal_item_and_keeps_machine_url_private(tmp_path):
    class FileFieldSession(Session):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/crm.deal.fields.json"):
                result = super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)
                result.data["result"]["UF_CRM_DOC"] = {"type": "file", "isMultiple": True}
                return result
            if url.endswith("/crm.deal.list.json"):
                result = super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)
                result.data["result"][0]["UF_CRM_DOC"] = [44]
                return result
            if url.endswith("/crm.item.get.json"):
                assert json == {"entityTypeId": 2, "id": 11, "useOriginalUfNames": "Y"}
                return Response({"result": {"item": {"id": 11, "UF_CRM_DOC": [{
                    "id": 44, "urlMachine":
                    "https://microchops.bitrix24.by/rest/crm.controller.item.getFile.json?auth=PRIVATE&token=SIGNED"
                }]}}})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    output = tmp_path / "private"
    summary = module.export(WEBHOOK, output, session=FileFieldSession())
    assert summary["crm_file_items"]["records"] == 1
    private_row = json.loads(next((output / "crm_file_items").glob("*.json")).read_text(encoding="utf-8"))
    assert private_row["fields"]["UF_CRM_DOC"][0]["id"] == "44"
    assert "SIGNED" in private_row["fields"]["UF_CRM_DOC"][0]["urlMachine"]
    assert "SIGNED" not in (output / "manifest.json").read_text(encoding="utf-8")


def test_crm_file_binary_phase_saves_html_attachment_with_source_link(tmp_path):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata, crm_file_items=[{"entity_type": "deals", "entity_id": "11",
                                         "file_field_names": ["UF_CRM_DOC"], "fields": {
        "UF_CRM_DOC": [{"id": "44", "urlMachine":
                        "https://microchops.bitrix24.by/rest/crm.controller.item.getFile.json?auth=PRIVATE&token=OLD"}]
    }}])

    class FileBinarySession(BinarySession):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/crm.item.get.json"):
                assert json == {"entityTypeId": 2, "id": 11, "useOriginalUfNames": "Y"}
                return Response({"result": {"item": {"id": 11, "UF_CRM_DOC": {
                    "id": 44, "urlMachine":
                    "https://microchops.bitrix24.by/rest/crm.controller.item.getFile.json?auth=PRIVATE&token=FRESH"
                }}}})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

        def get(self, url, *, stream, timeout, allow_redirects, headers):
            if "crm.controller.item.getFile" in url:
                assert "FRESH" in url and "OLD" not in url
                self.downloads.append(url)
                return BinaryResponse(b"<html>FILE</html>\n", content_type="text/html",
                                      disposition='attachment; filename="file.html"')
            return super().get(url, stream=stream, timeout=timeout,
                               allow_redirects=allow_redirects, headers=headers)

    output = tmp_path / "binaries"
    summary = module.export_binaries(WEBHOOK, metadata, output, session=FileBinarySession())
    assert summary["binary_files"]["records"] == 3
    assert summary["binary_links"]["records"] == 4
    assert b"<html>FILE</html>\n" in [path.read_bytes() for path in (output / "binary_files").glob("*.bin")]
    assert "SIGNED" not in (output / "manifest.json").read_text(encoding="utf-8")


def test_crm_file_binary_phase_refreshes_each_url_after_previous_download(tmp_path):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata, crm_file_items=[{
        "entity_type": "deals", "entity_id": "11", "file_field_names": ["UF_CRM_DOC"],
        "fields": {"UF_CRM_DOC": [
            {"id": "44", "urlMachine": "https://microchops.bitrix24.by/rest/crm.controller.item.getFile.json?token=OLD1"},
            {"id": "45", "urlMachine": "https://microchops.bitrix24.by/rest/crm.controller.item.getFile.json?token=OLD2"},
        ]},
    }])

    class ExpiringUrls(BinarySession):
        def __init__(self):
            super().__init__()
            self.refresh_count = 0

        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/crm.item.get.json"):
                self.refresh_count += 1
                token = f"FRESH{self.refresh_count}"
                return Response({"result": {"item": {"id": 11, "UF_CRM_DOC": [
                    {"id": 44, "urlMachine": f"https://microchops.bitrix24.by/rest/crm.controller.item.getFile.json?token={token}_44"},
                    {"id": 45, "urlMachine": f"https://microchops.bitrix24.by/rest/crm.controller.item.getFile.json?token={token}_45"},
                ]}}})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

        def get(self, url, *, stream, timeout, allow_redirects, headers):
            if "crm.controller.item.getFile" in url:
                crm_downloads = sum("crm.controller.item.getFile" in entry
                                    for entry in self.downloads)
                expected = f"FRESH{crm_downloads + 1}"
                if expected not in url:
                    return BinaryResponse(b"expired", content_type="text/html")
                self.downloads.append(url)
                return BinaryResponse(b"FILE")
            return super().get(url, stream=stream, timeout=timeout,
                               allow_redirects=allow_redirects, headers=headers)

    session = ExpiringUrls()
    summary = module.export_binaries(WEBHOOK, metadata, tmp_path / "binaries", session=session)
    assert summary["binary_files"]["records"] == 4
    assert session.refresh_count == 2
    assert len(session.downloads) == 4


def test_crm_file_phase_rejects_legacy_vs_universal_missing_field(tmp_path):
    class MissingUniversal(Session):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/crm.deal.fields.json"):
                result = super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)
                result.data["result"]["UF_CRM_DOC"] = {"type": "file"}
                return result
            if url.endswith("/crm.deal.list.json"):
                return Response({"result": [{"ID": "11", "UF_CRM_DOC": 44}]})
            if url.endswith("/crm.item.get.json"):
                return Response({"result": {"item": {"id": 11}}})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    output = tmp_path / "private"
    with pytest.raises(module.ExportError, match="CRM_FILE_ID_MISMATCH"):
        module.export(WEBHOOK, output, session=MissingUniversal())
    assert not (output / "manifest.json").exists()


def test_crm_file_phase_rejects_file_id_drift_before_binary_download(tmp_path):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata, crm_file_items=[{
        "entity_type": "deals", "entity_id": "11", "file_field_names": ["UF_CRM_DOC"],
        "fields": {"UF_CRM_DOC": [{"id": "44", "urlMachine":
            "https://microchops.bitrix24.by/rest/crm.controller.item.getFile.json?token=OLD"}]},
    }])

    class ChangedFile(BinarySession):
        def post(self, url, *, json, timeout, allow_redirects):
            if url.endswith("/crm.item.get.json"):
                return Response({"result": {"item": {"id": 11, "UF_CRM_DOC": {
                    "id": 45, "urlMachine":
                    "https://microchops.bitrix24.by/rest/crm.controller.item.getFile.json?token=FRESH"
                }}}})
            return super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)

    session = ChangedFile()
    output = tmp_path / "binaries"
    with pytest.raises(module.ExportError, match="CRM_FILE_SOURCE_CHANGED"):
        module.export_binaries(WEBHOOK, metadata, output, session=session)
    assert session.downloads == []
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize("body,mime", [
    (b"<html>FILE</html>\n", "text/html"),
    (b'{"valid":true}', "application/json"),
])
def test_binary_phase_allows_declared_text_file_with_verified_size(tmp_path, body, mime):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata)

    class HtmlFileSession(BinarySession):
        def post(self, url, *, json, timeout, allow_redirects):
            result = super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)
            if url.endswith("/disk.file.get.json"):
                result.data["result"]["SIZE"] = str(len(body))
            return result

    session = HtmlFileSession(response=BinaryResponse(
        body, content_type=mime,
        disposition='attachment; filename="export"',
    ))
    output = tmp_path / "binaries"
    summary = module.export_binaries(WEBHOOK, metadata, output, session=session)
    assert summary["binary_files"]["records"] == 2
    assert body in [path.read_bytes() for path in (output / "binary_files").glob("*.bin")]


def test_binary_phase_rejects_redirect_and_stream_failure_without_partial_file(tmp_path):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata)

    class Redirect(BinaryResponse):
        status_code = 302

    for response, expected in [(Redirect(), "BINARY_HTTP_302"),
                               (BinaryResponse(), "BINARY_NETWORK_ERROR")]:
        if expected == "BINARY_NETWORK_ERROR":
            def interrupted(chunk_size):
                yield b"PRIVATE_PARTIAL"
                raise requests.ConnectionError("PRIVATE_URL")
            response.iter_content = interrupted
        session = BinarySession(response=response)
        output = tmp_path / ("redirect" if expected == "BINARY_HTTP_302" else "interrupted")
        with pytest.raises(module.ExportError, match=expected) as exc:
            module.export_binaries(WEBHOOK, metadata, output, session=session)
        assert "PRIVATE_URL" not in str(exc.value)
        assert not list((output / "binary_files").glob("*.bin"))
        assert not (output / "manifest.json").exists()
        assert response.closed


def test_binary_phase_rejects_wrong_task_attachment_owner(tmp_path):
    metadata = tmp_path / "metadata"
    _binary_metadata(metadata)

    class WrongOwner(BinarySession):
        def post(self, url, *, json, timeout, allow_redirects):
            result = super().post(url, json=json, timeout=timeout, allow_redirects=allow_redirects)
            if url.endswith("/disk.attachedObject.get.json"):
                result.data["result"]["ENTITY_ID"] = "999"
            return result

    with pytest.raises(module.ExportError, match="TASK_ATTACHMENT_MISMATCH"):
        module.export_binaries(WEBHOOK, metadata, tmp_path / "binaries", session=WrongOwner())


@pytest.mark.parametrize("value", ["n", "N9", "n0", "n9x"])
def test_task_attachment_prefix_rejects_malformed_ids(value):
    with pytest.raises(module.ExportError, match="BAD_TASK_ATTACHMENT_ID"):
        module._task_attachment_id(value)
