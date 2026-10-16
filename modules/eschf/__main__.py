"""Local-only preview: python -m modules.eschf BUNDLE.json --out NEW_DIRECTORY."""

import argparse
import json
from pathlib import Path

from modules.eschf.preparation import Candidate, PartySnapshot, prepare, validate_xsd

SCHEMA_SHA256 = "01cd10900994bd7cde998faa5a178754388cd1b46adc30c3ff844e9754623867"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.bundle.stat().st_size > 2_000_000:
        parser.error("bundle exceeds 2 MB")
    data = json.loads(args.bundle.read_text(encoding="utf-8"))
    candidate = Candidate.model_validate(data["candidate"])
    records = tuple(PartySnapshot.model_validate(p) for p in data["reference_records"])
    prepared = prepare(candidate, data["source_snapshot"], data["source_original_html"], records)
    validate_xsd(prepared.unsigned_xml, Path(__file__).parent / "xsd/MNSATI_original.xsd",
                 SCHEMA_SHA256)
    args.out.mkdir(parents=True, exist_ok=False)  # Never overwrite an existing prepared version.
    (args.out / "candidate.xml").write_bytes(prepared.unsigned_xml)
    (args.out / "snapshot.json").write_bytes(prepared.snapshot)
    report = {
        "state": "unsigned_candidate_only", "xsd_valid": True,
        "portal_business_rules_verified": False, "portal_dictionary_verified": False,
        "signed": False, "sent": False,
        "snapshot_sha256": prepared.snapshot_sha256,
        "unsigned_xml_sha256": prepared.unsigned_xml_sha256,
        "identity_key": prepared.identity_key,
        "notice": "Локальный предпросмотр. ЭСЧФ не подписан и не выставлен.",
        "provider": candidate.provider.model_dump(), "recipient": candidate.recipient.model_dump(),
    }
    (args.out / "preview.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    print(report["notice"])
    print(args.out.resolve())


if __name__ == "__main__":
    main()
