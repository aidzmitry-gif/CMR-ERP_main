"""Build locally; exercise a separately compiled NONNATIVE backend and admission rejection only."""

import hashlib
import json
import os
import shutil
import struct
import subprocess
import uuid
from pathlib import Path

import pytest

from integrations.onec_eschf.isolated import package

HOST = package.HERE / "host"
POWERSHELL = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def bundle():
    if os.name != "nt":
        pytest.skip("Win32 Job Object tests require Windows; no native 1C needed")
    builds = HOST / "builds"
    builds.mkdir(exist_ok=True)
    output = builds / ("build-" + uuid.uuid4().hex)
    env = dict(os.environ, PSModulePath=str(POWERSHELL.parent / "Modules"))
    result = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-File",
                             str(HOST / "build.ps1"), "-NewOutputDirectory", str(output)],
                            capture_output=True, timeout=30, env=env, check=False)
    assert result.returncode == 0, result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")
    assert output.is_dir()
    # Keep the measured final EXEs/provenance for independent review; no deterministic hash claim.
    return output


@pytest.fixture
def scratch():
    path = HOST / (".synthetic-" + uuid.uuid4().hex)
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        assert path.resolve().parent == HOST
        assert path.name.startswith(".synthetic-")
        shutil.rmtree(path)


def run_synthetic(bundle, scratch, scenario):
    result = subprocess.run([str(bundle / "eschf-probe-synthetic.exe"), "--synthetic-case", scenario,
                             "--evidence-parent", str(scratch)], capture_output=True,
                            timeout=15, check=False)
    assert result.stdout, result.stderr.decode(errors="replace")
    index = json.loads(result.stdout)
    receipt_path = Path(index["receipt"])
    assert receipt_path.resolve().parent.parent == scratch
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["scope"] == "synthetic_nonnative"
    assert receipt["native_com_invoked"] is False and receipt["AC03"] is False
    assert receipt["broker_boundary_verified"] is False
    assert receipt["job_assigned_before_resume"] is True
    assert receipt["cleanup_confirmed"] is True
    assert receipt["worker_pid"] > 0
    # An owned process handle already confirmed exit; PID is diagnostic, never a cleanup target.
    return result, receipt, receipt_path.parent


def test_build_provenance_exact_hashes_and_x64(bundle):
    receipt = json.loads((bundle / "build-provenance.json").read_text(encoding="utf-8"))
    assert receipt["completed"] is True and receipt["scope"] == "local_build_only"
    assert receipt["native_com_invoked"] is False and receipt["nt63_runtime_verified"] is False
    assert receipt["deterministic_binary_claim"] is False
    assert receipt["compiler_sha256"] == digest(Path(receipt["compiler_path"]))
    assert receipt["source_sha256"] == digest(HOST / "FixedComHost.cs")
    assert receipt["build_script_sha256"] == digest(HOST / "build.ps1")
    assert {row["backend"] for row in receipt["outputs"]} == {"production", "synthetic"}
    for row in receipt["references"]:
        assert row["sha256"] == digest(Path(row["path"]))
    for row in receipt["outputs"]:
        raw = (bundle / row["file"]).read_bytes()
        assert row["sha256"] == hashlib.sha256(raw).hexdigest()
        pe = struct.unpack_from("<I", raw, 0x3C)[0]
        assert raw[pe:pe + 4] == b"PE\0\0"
        assert struct.unpack_from("<H", raw, pe + 4)[0] == 0x8664
        assert struct.unpack_from("<H", raw, pe + 24)[0] == 0x20B
        assert "/platform:x64" in row["arguments"] and "/langversion:5" in row["arguments"]
        assert ("/define:SYNTHETIC_BACKEND" in row["arguments"]) == (row["backend"] == "synthetic")


@pytest.mark.parametrize("args", [[], ["--synthetic-case", "success", "--evidence-parent", "unused"],
                                  ["--worker", "missing"], ["--approved-p2", "missing"]])
def test_production_without_exact_admission_never_activates_com(bundle, args):
    result = subprocess.run([str(bundle / "eschf-probe.exe"), *args], capture_output=True,
                            timeout=5, check=False)
    assert result.returncode == 64
    error = json.loads(result.stderr)
    assert error["native_activation_attempted"] is False
    assert error["AC03"] is False


@pytest.mark.parametrize("case", ["wrong_hash", "approved_flag", "server_target", "wrong_kind"])
def test_admission_boundary_rejects_before_activation(bundle, scratch, case):
    data = {"kind": "CRM-ESCHF-001/P2/fixed-host-context-probe-v1", "target": package.TARGET,
            "host": "1CSRV", "authorization_reference": "synthetic-not-an-approval"}
    if case == "approved_flag":
        data = {"approved": True, "account": "service"}
    elif case == "server_target":
        data["target"] = 'Srvr="localhost";Ref="ka_copy";'
    elif case == "wrong_kind":
        data["kind"] = "unreviewed"
    path = scratch / "synthetic-admission.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    claimed_hash = "0" * 64 if case == "wrong_hash" else digest(path)
    result = subprocess.run([str(bundle / "eschf-probe.exe"), "--approved-p2", str(path),
                             "--approved-p2-sha256", claimed_hash], capture_output=True,
                            timeout=5, check=False)
    assert result.returncode == 64
    assert json.loads(result.stderr)["native_activation_attempted"] is False


def test_synthetic_success_has_job_membership_before_backend(bundle, scratch):
    result, receipt, _ = run_synthetic(bundle, scratch, "success")
    assert result.returncode == 0 and receipt["complete"] is True
    assert receipt["result"]["scenario"] == "success"


@pytest.mark.parametrize("case,expected", [("hang", "worker_deadline"), ("output", "output_limit")])
def test_job_cleanup_on_hang_or_output_limit(bundle, scratch, case, expected):
    result, receipt, _ = run_synthetic(bundle, scratch, case)
    assert result.returncode == 1 and receipt["complete"] is False
    assert receipt["failure"] == expected


def test_os_process_memory_limit(bundle, scratch):
    result, receipt, _ = run_synthetic(bundle, scratch, "memory")
    assert result.returncode == 0 and receipt["complete"] is True
    assert receipt["result"]["memory_blocked"] is True


def test_job_rejects_ordinary_child_creation(bundle, scratch):
    result, receipt, directory = run_synthetic(bundle, scratch, "child")
    assert result.returncode == 0 and receipt["complete"] is True
    assert receipt["result"]["child_blocked"] is True
    assert receipt["result"]["child_error"] != 0
    assert not (directory / "leaf.txt").exists()


def test_guard_order_and_fixed_native_calls_are_reviewable():
    source = (HOST / "FixedComHost.cs").read_text(encoding="utf-8-sig")
    supervisor = source[source.index("static int Supervise("):source.index("static int Worker(")]
    assert supervisor.index("0x08000004") < supervisor.index("AssignProcessToJobObject") < supervisor.index("ResumeThread")
    assert '"native_com_invoked", syntheticCase == null ? (object)null : false' in supervisor
    worker = source[source.index("static int Worker("):source.index("static Dictionary<string, object> Synthetic(")]
    assert worker.index("exact_job_limits") < worker.index("Approval(Text(request") < worker.index("NativeProbe(approval)")
    native = source[source.index("static Dictionary<string, object> NativeProbe("):]
    assert native.index("com_version_hash") < native.index("Activator.CreateInstance") < native.index('"Connect"')
    assert '"File=\\\"D:\\\\CRM-ESCHF-001-Isolated\\\\ka_eschf_test\\\";"' in native
    approval = source[source.index("static Dictionary<string, object> Approval("):source.index("[StructLayout")]
    for boundary in ("source_approval_binding", "account_setup_binding", "host_guard", "admin_token",
                     "isolation_binding", "initialization_scope", "artifact_hash", "seed_receipt",
                     "image_hash", "key_access_evidence", "egress_evidence", "child_process_evidence"):
        assert boundary in approval


def test_packager_includes_only_production_host_with_provenance(bundle, scratch):
    seed = scratch / "Configuration.xml"
    seed.write_text(f'<MetaDataObject xmlns="{package.NS}" version="2.11"><Configuration uuid="synthetic">'
                    f'<Properties><Name>{package.BASE_NAME}</Name><Version>{package.BASE_VERSION}</Version>'
                    '</Properties><ChildObjects><CommonModule>SyntheticExisting</CommonModule>'
                    '</ChildObjects></Configuration></MetaDataObject>', encoding="utf-8")
    manifest = package.build(seed, digest(seed), scratch / "new-patch", bundle)
    assert manifest["fixed_host"]["sha256"] == digest(bundle / "eschf-probe.exe")
    assert manifest["fixed_host"]["nt63_runtime_verified"] is False
    assert not any("synthetic.exe" in key for key in manifest["files"])
    assert manifest["files"]["FixedHost/build-provenance.json"] == digest(bundle / "build-provenance.json")
