"""Export the two approved 1C catalogs into a private server directory.

Only counts and digests are printed. Record bodies and diagnostics stay on the
server. Run this in a one-off container with /private bound to a mode-0700 host
directory and connectors/.env bound read-only.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

CATALOGS = ("Catalog_Контрагенты", "Catalog_Номенклатура")
PAGE_SIZE = 500


class ExportError(Exception):
    """An error code safe to expose without a record body or source URL."""


def _page(session: requests.Session, url: str, skip: int) -> list[dict[str, Any]]:
    params = {"$format": "json", "$top": PAGE_SIZE, "$skip": skip, "$orderby": "Ref_Key"}
    for attempt in range(3):
        try:
            response = session.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            if attempt == 2:
                raise ExportError("NETWORK_" + type(exc).__name__) from None
            time.sleep(2**attempt)
            continue
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
            time.sleep(2**attempt)
            continue
        if response.status_code != 200:
            raise ExportError("HTTP_" + str(response.status_code))
        try:
            rows = response.json()["value"]
        except (ValueError, KeyError, TypeError):
            raise ExportError("BAD_JSON") from None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ExportError("BAD_ROWS")
        return rows
    raise ExportError("RETRY_EXHAUSTED")


def _persist(folder: Path, catalog: str, row: dict[str, Any]) -> tuple[str, int, str]:
    source_id = row.get("Ref_Key")
    if not isinstance(source_id, str) or not source_id:
        raise ExportError("MISSING_REF")
    key = (catalog + ":" + source_id).encode("utf-8")
    filename = hashlib.sha256(key).hexdigest() + ".json"
    body = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    target = folder / filename
    temporary = folder / (filename + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(body)
    os.replace(temporary, target)
    return filename, len(body), digest


def export(base_url: str, username: str, password: str, output: Path,
           *, session: requests.Session | None = None) -> dict[str, dict[str, int | str]]:
    if not base_url or not username or not password:
        raise ExportError("CONFIG_MISSING")
    private_mode = 0o700 if os.name == "posix" else 0o777
    output.mkdir(mode=private_mode, parents=True, exist_ok=True)
    client = session or requests.Session()
    client.auth = (username, password)
    client.headers.update({"Accept": "application/json"})
    summary: dict[str, dict[str, int | str]] = {}
    for catalog in CATALOGS:
        folder = output / catalog
        folder.mkdir(mode=private_mode, exist_ok=True)
        seen: set[str] = set()
        files: list[tuple[str, int, str]] = []
        skip = 0
        while True:
            rows = _page(client, base_url.rstrip("/") + "/" + catalog, skip)
            for row in rows:
                ref = row.get("Ref_Key")
                if not isinstance(ref, str) or not ref:
                    raise ExportError("MISSING_REF")
                if ref in seen:
                    raise ExportError("DUPLICATE_REF")
                seen.add(ref)
                files.append(_persist(folder, catalog, row))
            skip += len(rows)
            if len(rows) < PAGE_SIZE:
                break
        if {path.name for path in folder.glob("*.json")} != {name for name, _, _ in files}:
            raise ExportError("STALE_FILES_USE_NEW_DIRECTORY")
        fingerprint = hashlib.sha256()
        for filename, size, digest in sorted(files):
            fingerprint.update(f"{filename}:{size}:{digest}\n".encode("ascii"))
        summary[catalog] = {"records": len(files), "bytes": sum(size for _, size, _ in files),
                            "sha256": fingerprint.hexdigest()}
    manifest = output / "manifest.json"
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, manifest)
    return summary


def main() -> int:
    os.umask(0o077)
    from dotenv import load_dotenv

    load_dotenv("/app/connectors/.env")
    try:
        summary = export(os.getenv("ONEC_BASE_URL", ""), os.getenv("ONEC_USER", ""),
                         os.getenv("ONEC_PASSWORD", ""), Path("/private"))
    except ExportError as exc:
        print("EXPORT_FAILED", str(exc))
        return 1
    for catalog, result in summary.items():
        print(catalog, result["records"], result["bytes"], result["sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
