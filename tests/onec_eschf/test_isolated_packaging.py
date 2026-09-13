"""Synthetic metadata, fake child processes; never COM, 1C or network."""

import base64
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from integrations.onec_eschf.isolated import package

RUNNER = package.HERE / "run-isolated.ps1"
PS = shutil.which("powershell.exe")


@pytest.fixture
def tmp_path():
    # pytest's Windows mkdir(0o700) removes this sandbox's access. Use inherited ACLs
    # on a fresh directory inside this packet; never touch the shared pytest temp root.
    path = package.HERE / (".synthetic-" + uuid.uuid4().hex)
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        if path.resolve().parent != package.HERE or not path.name.startswith(".synthetic-"):
            raise RuntimeError("synthetic cleanup escaped owned directory")
        shutil.rmtree(path)


def synthetic_seed():
    return (f'<?xml version="1.0" encoding="UTF-8"?>\r\n'
            f'<MetaDataObject xmlns="{package.NS}" version="2.11">\r\n'
            '<Configuration uuid="11111111-1111-4111-8111-111111111111">'
            f'<Properties><Name>{package.BASE_NAME}</Name>'
            f'<Version>{package.BASE_VERSION}</Version></Properties>'
            '<ChildObjects><CommonModule>ExistingSyntheticModule</CommonModule>'
            '</ChildObjects></Configuration></MetaDataObject>').encode()


def test_patch_preserves_all_original_bytes_and_bom():
    raw = b"\xef\xbb\xbf" + synthetic_seed()
    patched = package.prepare_patch(raw, package.digest(raw))
    addition = f"<CommonModule>{package.NAME}</CommonModule>\r\n".encode()
    assert patched.replace(addition, b"", 1) == raw
    root = ET.fromstring(patched)
    assert root.find(f".//{{{package.NS}}}CommonModule").text == "ExistingSyntheticModule"


@pytest.mark.parametrize("change", [
    lambda x: x.replace(b'version="2.11"', b'version="2.99"'),
    lambda x: x.replace(b"2.4.14.182", b"2.4.14.999"),
    lambda x: x.replace(package.BASE_NAME.encode(), b"DifferentConfiguration"),
    lambda x: x.replace(b"<Properties>", b"<Properties><Version>2.4.14.182</Version>"),
    lambda x: x.replace(b"</ChildObjects>", b"</ChildObjects><ChildObjects/>"),
    lambda x: x.replace(b"ExistingSyntheticModule", package.NAME.encode()),
    lambda x: x.replace(b"<Configuration ", b"<!DOCTYPE x><Configuration "),
    lambda x: x.replace(b"<Configuration ", b"<!ENTITY secret SYSTEM 'file:///x'><Configuration "),
    lambda x: x.replace(b"</ChildObjects>", b"</ChildObjects><!-- </ChildObjects> -->"),
])
def test_rejects_unsupported_or_ambiguous_seed(change):
    raw = change(synthetic_seed())
    with pytest.raises(ValueError):
        package.prepare_patch(raw, package.digest(raw))


def test_requires_exact_input_hash_and_bounded_xml():
    raw = synthetic_seed()
    with pytest.raises(ValueError, match="hash"):
        package.prepare_patch(raw, "0" * 64)
    raw += b" " * package.MAX_XML
    with pytest.raises(ValueError, match="oversized"):
        package.prepare_patch(raw, package.digest(raw))


def test_new_output_contains_only_reviewable_patch_and_hashes(tmp_path):
    seed = tmp_path / "Configuration.xml"
    raw = synthetic_seed()
    seed.write_bytes(raw)
    output = tmp_path / "new-package"
    manifest = package.build(seed, package.digest(raw), output)
    assert seed.read_bytes() == raw
    assert manifest["scope"] == "local_patch_only"
    assert manifest["runtime_validated"] is False
    assert manifest["target"] == package.TARGET
    assert len(manifest["files"]) == 4
    for name, digest in manifest["files"].items():
        assert package.digest((output / name).read_bytes()) == digest
    module = output / f"CommonModules/{package.NAME}/Ext/Module.bsl"
    accepted = (package.HERE.parent / "native_adapter.bsl").read_bytes()
    assert module.read_bytes().startswith(b"\xef\xbb\xbf" + accepted + b"\n\n")
    assert (output / "run-isolated.ps1").read_bytes().startswith(b"\xef\xbb\xbf")
    with pytest.raises(ValueError, match="new"):
        package.build(seed, package.digest(raw), output)
    assert seed.read_bytes() == raw


def test_failed_validation_creates_no_output(tmp_path):
    seed = tmp_path / "Configuration.xml"
    seed.write_bytes(synthetic_seed())
    with pytest.raises(ValueError):
        package.build(seed, "0" * 64, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_packager_rejects_privileged_metadata_before_writing(tmp_path, monkeypatch):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    for name in ("common-module.xml", "capture.bsl", "run-isolated.ps1"):
        shutil.copyfile(package.HERE / name, isolated / name)
    shutil.copyfile(package.HERE.parent / "native_adapter.bsl", tmp_path / "native_adapter.bsl")
    metadata = isolated / "common-module.xml"
    metadata.write_bytes(metadata.read_bytes().replace(
        b"<Privileged>false</Privileged>", b"<Privileged>true</Privileged>"))
    monkeypatch.setattr(package, "HERE", isolated)
    seed = tmp_path / "Configuration.xml"
    seed.write_bytes(synthetic_seed())
    with pytest.raises(ValueError, match="unsafe module flags"):
        package.build(seed, package.digest(seed.read_bytes()), tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_candidate_bytes_remain_explicitly_nonfinal():
    text = '<x>Беларусь\r\n😀</x>'
    plain = package.candidate_bytes(text, bom=False)
    bom = package.candidate_bytes(text, bom=True)
    assert plain["bytes"] == text.encode("utf-8")
    assert bom["bytes"] == b"\xef\xbb\xbf" + plain["bytes"]
    assert bom["sha256"] != plain["sha256"]
    assert plain["scope"] == bom["scope"] == "candidate_utf8_nonfinal"
    assert plain["native_byte_equality"] is False
    with pytest.raises(ValueError):
        package.candidate_bytes(text, bom="false")


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_ps(source, timeout=20):
    if PS is None:
        pytest.skip("Windows PowerShell not installed; native runtime never required")
    encoded = base64.b64encode(source.encode("utf-16le")).decode("ascii")
    # Do not inherit PowerShell 7's incompatible module path into Windows PowerShell 5.1.
    env = dict(os.environ, PSModulePath=str(Path(PS).parent / "Modules"))
    result = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, timeout=timeout, check=False, env=env)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[:3000]
    return result.stdout.decode("utf-8-sig")


def functions_prefix():
    return ("[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false); "
            f". {ps_quote(RUNNER)} -FunctionsOnly; ")


def test_powershell_parser_and_preconnect_guard_order():
    output = run_ps("$t=$null;$e=$null;[void][Management.Automation.Language.Parser]::ParseFile("
                    + ps_quote(RUNNER) + ",[ref]$t,[ref]$e); if(@($e).Count){throw 'parse'}; 'PASS'")
    assert "PASS" in output
    source = RUNNER.read_text(encoding="utf-8-sig")
    # COM has moved into the fixed, separately tested host. PowerShell only launches it.
    assert "New-Object -ComObject" not in source and ".Connect(" not in source
    assert "\\runtime\\eschf-probe.exe" in source
    launcher = source[source.index("# No COM activation in PowerShell."):]
    assert launcher.index("Assert-Approval") < launcher.index("Invoke-OwnedProcess")
    assert "--approved-p2-sha256" in launcher
    assert "regsvr32" not in source and "/S " not in source


def test_declarative_approved_flag_cannot_authorize_connect(tmp_path):
    approval = tmp_path / "fake-approval.json"
    raw = json.dumps({"approved": True, "account": "service"}).encode()
    approval.write_bytes(raw)
    output = run_ps(functions_prefix() + "try {Assert-Approval " + ps_quote(approval) + " "
                    + ps_quote(package.digest(raw)) + "; throw 'unexpected_success'} "
                    "catch { if($_.Exception.Message -ne 'exact_p2_required'){throw}; 'REJECTED' }")
    assert "REJECTED" in output


def test_receipt_hash_required_before_parsing(tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_text('{"approved":true}', encoding="utf-8")
    output = run_ps(functions_prefix() + "try {Read-BoundedJson " + ps_quote(receipt)
                    + " " + ps_quote("0" * 64) + "; throw 'unexpected_success'} "
                    "catch {if($_.Exception.Message -ne 'receipt_hash_guard'){throw}; 'REJECTED'}")
    assert "REJECTED" in output


def test_receipt_reads_hash_bound_utf8_bom_content(tmp_path):
    receipt = tmp_path / "synthetic-receipt.json"
    raw = b"\xef\xbb\xbf" + json.dumps({"text": "Беларусь"}, ensure_ascii=False).encode()
    receipt.write_bytes(raw)
    output = run_ps(functions_prefix() + "Read-BoundedJson " + ps_quote(receipt) + " "
                    + ps_quote(package.digest(raw)) + " | ConvertTo-Json -Compress")
    assert json.loads(output) == {"text": "Беларусь"}


def test_owned_short_process_completes_without_false_timeout(tmp_path):
    directory = tmp_path / "success"
    directory.mkdir()
    arguments = "-NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(
        "exit 0".encode("utf-16le")).decode("ascii")
    source = (functions_prefix() + "Invoke-OwnedProcess -Executable " + ps_quote(PS)
              + " -Arguments " + ps_quote(arguments) + " -Directory " + ps_quote(directory)
              + " -TimeoutSeconds 10 | ConvertTo-Json -Compress")
    result = json.loads(run_ps(source))
    assert result["Complete"] is True, json.dumps(result)
    assert result["CleanupConfirmed"] is True
    assert result["ExitCode"] == 0


@pytest.mark.parametrize("limit_kind", ["timeout", "output"])
def test_owned_subprocess_stopped_even_when_child_never_returns(tmp_path, limit_kind):
    # A sleeping PowerShell is a synthetic COM-hang substitute; no COM/network/1C is called.
    directory = tmp_path / limit_kind
    directory.mkdir()
    payload = ("[IO.File]::WriteAllBytes(" + ps_quote(directory / "synthetic-output.bin")
               + ",(New-Object byte[] 8192)); Start-Sleep -Seconds 30"
               if limit_kind == "output" else "Start-Sleep -Seconds 30")
    arguments = "-NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(
        payload.encode("utf-16le")).decode("ascii")
    timeout = 10 if limit_kind == "output" else 1
    byte_limit = 1024 if limit_kind == "output" else 1048576
    source = (functions_prefix() + "$r=Invoke-OwnedProcess -Executable " + ps_quote(PS)
              + " -Arguments " + ps_quote(arguments) + " -Directory " + ps_quote(directory)
              + f" -TimeoutSeconds {timeout} -MaxOutputBytes {byte_limit}; "
              "$r.ProcessStillAlive=[bool](Get-Process -Id $r.Pid -ErrorAction SilentlyContinue); "
              "$r | ConvertTo-Json -Compress")
    result = json.loads(run_ps(source))
    assert result["Complete"] is False
    assert result["CleanupConfirmed"] is True
    assert result["ProcessStillAlive"] is False
    assert result["Failure"] == ("owned_process_deadline" if limit_kind == "timeout"
                                 else "owned_output_limit")
