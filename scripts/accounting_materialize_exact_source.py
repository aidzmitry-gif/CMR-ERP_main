"""Materialize the committed CRM ERP tree and its pinned local gitlinks.

This is a local source check, not a deployment or a substitute for publishing
the exact commits. The destination must not exist; the caller owns its cleanup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE)


def _materialize(repo: Path, revision: str, destination: Path) -> dict[str, object]:
    if _git(repo, "cat-file", "-t", revision).strip() != b"commit":
        raise ValueError(f"{repo}: pinned object is not a commit")
    tree = _git(repo, "rev-parse", f"{revision}^{{tree}}").decode().strip()
    files = 0
    byte_count = 0
    process = subprocess.Popen(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    try:
        for record in _git(repo, "ls-tree", "-r", "-z", revision).split(b"\0"):
            if not record:
                continue
            metadata, name = record.split(b"\t", 1)
            mode, kind, object_id = metadata.decode().split()
            if kind == "commit":  # A gitlink has no file bytes in the root tree.
                continue
            if kind != "blob" or mode == "120000":
                raise ValueError(f"unsupported Git tree entry: {name!r}")
            member = PurePosixPath(name.decode())
            if member.is_absolute() or any(part in ("", ".", "..") for part in member.parts):
                raise ValueError(f"unsafe Git tree path: {name!r}")
            target = destination.joinpath(*member.parts)
            if target.exists():
                raise ValueError(f"Git blob would overwrite a file: {target}")
            process.stdin.write(object_id.encode() + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().strip().split()
            if len(header) != 3 or header[0].decode() != object_id or header[1] != b"blob":
                raise ValueError(f"unexpected git cat-file response: {header!r}")
            data = process.stdout.read(int(header[2]))
            if process.stdout.read(1) != b"\n":
                raise ValueError(f"truncated git cat-file response: {member}")
            blob = b"blob " + str(len(data)).encode() + b"\0" + data
            if hashlib.sha1(blob).hexdigest() != object_id:
                raise ValueError(f"Git blob hash mismatch: {member}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            files += 1
            byte_count += len(data)
    finally:
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError(f"git cat-file failed: {process.stderr.read()!r}")
    return {
        "commit": revision,
        "tree": tree,
        "file_count": files,
        "verified_blobs": files,
        "byte_count": byte_count,
    }


def _gitlinks(repo: Path, revision: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for record in _git(repo, "ls-tree", "-z", f"{revision}:modules").split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, kind, object_id = metadata.decode().split()
        if mode == "160000" and kind == "commit":
            result[name.decode()] = object_id
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="nonexistent clean source directory")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--module-store", type=Path, required=True)
    parser.add_argument("--wms-repo", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve(strict=True)
    destination = args.destination.resolve()
    if destination.exists():
        raise ValueError(f"destination already exists: {destination}")
    root_commit = _git(root, "rev-parse", "HEAD").decode().strip()
    links = _gitlinks(root, root_commit)
    if len(links) != 10 or "wms" not in links:
        raise ValueError(f"expected ten pinned module gitlinks including WMS; got {links!r}")

    # Validate every object before creating any output.
    for name, revision in links.items():
        source = args.wms_repo if name == "wms" else args.module_store / name
        if _git(source, "cat-file", "-t", revision).strip() != b"commit":
            raise ValueError(f"{name}: missing pinned commit {revision}")

    destination.mkdir(parents=True)
    records: dict[str, dict[str, object]] = {"root": _materialize(root, root_commit, destination)}
    for name, revision in sorted(links.items()):
        source = args.wms_repo if name == "wms" else args.module_store / name
        module_destination = destination / "modules" / name
        if module_destination.exists() and any(module_destination.iterdir()):
            raise ValueError(f"root archive contains files in gitlink {name}")
        records[name] = _materialize(source, revision, module_destination)
    print(json.dumps({"destination": str(destination), "sources": records}, indent=2))


if __name__ == "__main__":
    main()
