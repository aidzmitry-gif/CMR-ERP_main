"""Read-only structural preflight for a monthly XLSX timesheet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from modules.accounting.timesheet_preflight import UnsupportedWorkbook, scan

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="monthly XLSX timesheet (read only)")
    parser.add_argument("--month", required=True, help="expected period, YYYY-MM")
    args = parser.parse_args()
    try:
        result = scan(args.file, args.month)
    except (OSError, UnsupportedWorkbook) as exc:
        print(json.dumps({"structure_ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["structure_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
