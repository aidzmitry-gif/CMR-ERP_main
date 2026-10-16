"""Offline, exact-seed transformer. Never opens 1C or creates an executable full seed."""

import argparse
import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
NS = "http://v8.1c.ru/8.3/MDClasses"
NAME = "CRMЭСЧФИзолированныйТест"
UUID = "4a4204e1-bad8-4f37-854a-f0b1495f8b61"
MARKER = f"CRM-ESCHF-001/{UUID}"
TARGET = r"D:\CRM-ESCHF-001-Isolated\ka_eschf_test"
BASE_NAME = "КомплекснаяАвтоматизацияДляБеларуси"
BASE_VERSION = "2.4.14.182"
NATIVE_HASH = "b57f6649dad9196daf001b52e1fe299c8bf6bbf281d8dd4e44f07deba76f3494"
MAX_XML = 2 * 1024 * 1024


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def checked_xml(raw: bytes) -> ET.Element:
    if len(raw) > MAX_XML or re.search(br"<!\s*(DOCTYPE|ENTITY)\b", raw, re.I):
        raise ValueError("unsafe or oversized metadata XML")
    text = raw.decode("utf-8-sig", errors="strict")
    root = ET.fromstring(text)
    if root.tag != f"{{{NS}}}MetaDataObject" or root.get("version") != "2.11":
        raise ValueError("unsupported metadata format")
    return root


def one(parent: ET.Element, name: str) -> ET.Element:
    items = parent.findall(f"{{{NS}}}{name}")
    if len(items) != 1:
        raise ValueError(f"expected one {name}")
    return items[0]


def prepare_patch(seed_xml: bytes, expected_sha256: str) -> bytes:
    """Preserve every original byte; accept only a bounded unprefixed seed shape."""
    if digest(seed_xml) != expected_sha256:
        raise ValueError("seed Configuration.xml hash mismatch")
    root = checked_xml(seed_xml)
    configuration = one(root, "Configuration")
    if len(root) != 1:
        raise ValueError("unexpected metadata siblings")
    properties = one(configuration, "Properties")
    if (one(properties, "Name").text, one(properties, "Version").text) != (
        BASE_NAME, BASE_VERSION
    ):
        raise ValueError("unexpected seed identity/version")
    children = one(configuration, "ChildObjects")
    if len(children) == 0 or any(not child.tag.startswith(f"{{{NS}}}") for child in children):
        raise ValueError("unsupported child metadata")
    if any((child.text or "").strip() == NAME for child in children):
        raise ValueError("test module already exists")
    # No root XML synthesis or reserialization. Reject ambiguous/prefixed insertion points.
    closing = b"</ChildObjects>"
    if seed_xml.count(closing) != 1:
        raise ValueError("ambiguous ChildObjects closing tag")
    ending = b"\r\n" if b"\r\n" in seed_xml else b"\n"
    inserted = f"<CommonModule>{NAME}</CommonModule>".encode() + ending
    patched = seed_xml.replace(closing, inserted + closing, 1)
    result = one(one(checked_xml(patched), "Configuration"), "ChildObjects")
    if sum(item.tag == f"{{{NS}}}CommonModule" and item.text == NAME for item in result) != 1:
        raise ValueError("patch did not insert the exact module")
    return patched


def candidate_bytes(xml_text: str, *, bom: bool) -> dict:
    """Explicit transport experiment, never evidence of native/pre-sign byte equality."""
    if not isinstance(xml_text, str) or type(bom) is not bool:
        raise ValueError("explicit string and BOM hypothesis required")
    raw = xml_text.encode("utf-8-sig" if bom else "utf-8", errors="strict")
    return {"scope": "candidate_utf8_nonfinal", "native_byte_equality": False,
            "bytes": raw, "sha256": digest(raw), "bom": bom}


def build(seed: Path, expected_sha256: str, output: Path, host_bundle: Path | None = None) -> dict:
    """Write ONLY a new local output directory; never overwrite the supplied seed."""
    if seed.is_symlink() or not seed.is_file() or seed.stat().st_size > MAX_XML:
        raise ValueError("invalid seed input")
    seed_raw = seed.read_bytes()
    patched = prepare_patch(seed_raw, expected_sha256)
    native = (HERE.parent / "native_adapter.bsl").read_bytes()
    if digest(native) != NATIVE_HASH:
        raise ValueError("accepted native body changed")
    metadata = (HERE / "common-module.xml").read_bytes()
    module = one(checked_xml(metadata), "CommonModule")
    if module.get("uuid") != UUID or one(one(module, "Properties"), "Name").text != NAME:
        raise ValueError("module identity mismatch")
    properties = one(module, "Properties")
    flags = {"Server": "true", "ExternalConnection": "true", "Global": "false",
             "Privileged": "false", "ServerCall": "false", "ClientManagedApplication": "false",
             "ClientOrdinaryApplication": "false", "ReturnValuesReuse": "DontUse"}
    if any(one(properties, flag).text != value for flag, value in flags.items()):
        raise ValueError("unsafe module flags")
    capture = (HERE / "capture.bsl").read_bytes()
    # Observed Designer BSL exports use UTF-8 BOM; preserve accepted body after the BOM.
    body = b"\xef\xbb\xbf" + native + b"\n\n" + capture
    files = {
        "Configuration.xml": patched,
        f"CommonModules/{NAME}.xml": metadata,
        f"CommonModules/{NAME}/Ext/Module.bsl": body,
        "run-isolated.ps1": (HERE / "run-isolated.ps1").read_bytes(),
    }
    manifest = {"scope": "local_patch_only", "runtime_validated": False,
                "target": TARGET, "configuration_name": BASE_NAME,
                "configuration_version": BASE_VERSION, "module_name": NAME,
                "marker": MARKER, "seed_configuration_sha256": digest(seed_raw),
                "accepted_native_sha256": digest(native),
                "files": {name: digest(raw) for name, raw in files.items()}}
    if host_bundle is not None:
        provenance_raw = (host_bundle / "build-provenance.json").read_bytes()
        provenance = json.loads(provenance_raw)
        if (provenance.get("completed") is not True
                or provenance.get("nt63_runtime_verified") is not False
                or provenance.get("scope") != "local_build_only"
                or provenance.get("source_sha256") != digest(
                    (HERE / "host/FixedComHost.cs").read_bytes())):
            raise ValueError("unverified or stale fixed host bundle")
        production = [item for item in provenance["outputs"] if item["backend"] == "production"]
        if len(production) != 1 or production[0]["file"] != "eschf-probe.exe":
            raise ValueError("exact production host required")
        host_raw = (host_bundle / "eschf-probe.exe").read_bytes()
        if digest(host_raw) != production[0]["sha256"] or not host_raw.startswith(b"MZ"):
            raise ValueError("fixed host hash mismatch")
        files["FixedHost/eschf-probe.exe"] = host_raw
        files["FixedHost/build-provenance.json"] = provenance_raw
        manifest["fixed_host"] = {"sha256": digest(host_raw), "nt63_runtime_verified": False}
        manifest["files"] = {name: digest(raw) for name, raw in files.items()}
    # Require a pre-existing local parent and a wholly new direct output directory.
    parent = output.parent.resolve(strict=True)
    if output.name in {"", ".", ".."} or output.is_symlink() or output.exists():
        raise ValueError("output must be new")
    if seed.resolve().is_relative_to(parent / output.name):
        raise ValueError("output must not contain the seed")
    output = parent / output.name
    output.mkdir(exist_ok=False)
    for name, raw in files.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(raw)
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-configuration", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--new-output", required=True, type=Path)
    parser.add_argument("--host-bundle", type=Path)
    args = parser.parse_args()
    build(args.seed_configuration, args.expected_sha256, args.new_output, args.host_bundle)
