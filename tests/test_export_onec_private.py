"""Synthetic checks for the server-only 1C catalog snapshot."""
from __future__ import annotations

import json

import pytest

from scripts.export_onec_private import ExportError, export


class Response:
    status_code = 200

    def __init__(self, rows):
        self.rows = rows

    def json(self):
        return {"value": self.rows}


class Session:
    def __init__(self, catalogs):
        self.catalogs = catalogs
        self.headers = {}
        self.calls = []
        self.auth = None

    def get(self, url, *, params, timeout):
        self.calls.append((url, params["$skip"], timeout))
        return Response(self.catalogs[url.rsplit("/", 1)[-1]])


def test_two_catalogs_stay_in_private_files_and_repeat_has_same_manifest(tmp_path, capsys):
    source = {
        "Catalog_Контрагенты": [{"Ref_Key": "cp-1", "Description": "Private Customer"}],
        "Catalog_Номенклатура": [{"Ref_Key": "sku-1", "Description": "Private Product"}],
    }
    session = Session(source)
    first = export("https://onec.invalid/odata", "user", "secret", tmp_path, session=session)
    second = export("https://onec.invalid/odata", "user", "secret", tmp_path, session=session)

    assert first == second
    assert [first[name]["records"] for name in source] == [1, 1]
    assert session.auth == ("user", "secret")
    assert len(session.calls) == 4
    assert "Private Customer" not in capsys.readouterr().out
    assert "Private Customer" in next((tmp_path / "Catalog_Контрагенты").glob("*.json")).read_text()
    assert json.loads((tmp_path / "manifest.json").read_text()) == first


def test_duplicate_ref_fails_without_publishing_manifest(tmp_path):
    session = Session({"Catalog_Контрагенты": [
        {"Ref_Key": "same"}, {"Ref_Key": "same"}], "Catalog_Номенклатура": []})
    with pytest.raises(ExportError, match="DUPLICATE_REF"):
        export("https://onec.invalid", "user", "secret", tmp_path, session=session)
    assert not (tmp_path / "manifest.json").exists()


def test_source_shrink_fails_closed_in_existing_directory(tmp_path):
    source = {"Catalog_Контрагенты": [{"Ref_Key": "a"}, {"Ref_Key": "b"}],
              "Catalog_Номенклатура": []}
    export("https://onec.invalid", "user", "secret", tmp_path, session=Session(source))
    source["Catalog_Контрагенты"] = [{"Ref_Key": "a"}]
    with pytest.raises(ExportError, match="STALE_FILES_USE_NEW_DIRECTORY"):
        export("https://onec.invalid", "user", "secret", tmp_path, session=Session(source))
