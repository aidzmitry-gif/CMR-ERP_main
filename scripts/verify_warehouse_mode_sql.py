"""Execute only new mode guards in an owned ephemeral local PostgreSQL container."""
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations/versions/crm_rel_001_wms_mode_01.py"
OWNER = "crm-rel-001-mode-" + uuid.uuid4().hex

def command(args, *, sql=None, check=True):
    result = subprocess.run(args, input=sql, text=True, capture_output=True, timeout=60)
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-1400:])
    return result

spec = importlib.util.spec_from_file_location("mode_migration", MIGRATION)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
statements = []
class Collector:
    execute = staticmethod(statements.append)
module.op = Collector
module.upgrade()
container = None
passed = []
try:
    container = command(["docker", "run", "--rm", "-d", "--network", "none", "--label", "crm.mode-test="+OWNER,
        "--tmpfs", "/var/lib/postgresql/data", "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:16-alpine"]).stdout.strip()
    if len(container) != 64 or any(c not in "0123456789abcdef" for c in container):
        raise RuntimeError("Invalid owned container identity")
    for attempt in range(40):
        if command(["docker", "exec", container, "pg_isready", "-U", "postgres"], check=False).returncode == 0:
            break
        time.sleep(.5)
    else:
        raise RuntimeError("Synthetic PostgreSQL did not become ready")
    def sql(statement, check=True):
        return command(["docker", "exec", "-i", container, "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-At"], sql=statement, check=check)
    sql("""CREATE SCHEMA accounting; CREATE SCHEMA wms;
    CREATE TABLE accounting.organization(id integer PRIMARY KEY);
    INSERT INTO accounting.organization VALUES(1);
    CREATE TABLE wms.warehouse_directory(id integer PRIMARY KEY, organization_id integer, name text, is_active boolean);
    INSERT INTO wms.warehouse_directory VALUES(1,1,'W',true);
    CREATE TABLE wms.invoice_reservation(document_id integer PRIMARY KEY, organization_id integer, snapshot jsonb);
    INSERT INTO wms.invoice_reservation VALUES(1,1,'{"allocations":[{"warehouse":"W"}]}');
    CREATE TABLE wms.physical_shipment_act(document_id integer, organization_id integer, snapshot jsonb);
    """)
    sql(";\n".join(statements))
    if "--concurrency-only" not in sys.argv:
        assert sql("SELECT wms_enabled FROM wms.warehouse_directory").stdout.strip() == "f"
        passed.append("default_off")
        assert sql("SELECT execution_modes IS NULL FROM wms.invoice_reservation WHERE document_id=1").stdout.strip() == "t"
        passed.append("legacy_null_preserved")
        sql("INSERT INTO wms.invoice_reservation VALUES(2,1,'{\"allocations\":[{\"warehouse\":\"W\"}]}','{\"W\":false}')")
        passed.append("exact_off_reservation")
        for name, modes in [("null_rejected", "NULL"), ("string_rejected", "'{\"W\":\"false\"}'"),
                            ("wrong_mode_rejected", "'{\"W\":true}'"), ("extra_warehouse_rejected", "'{\"W\":false,\"X\":false}'")]:
            result = sql("INSERT INTO wms.invoice_reservation VALUES(3,1,'{\"allocations\":[{\"warehouse\":\"W\"}]}',"+modes+")", check=False)
            assert result.returncode != 0 and "ERROR:" in result.stderr, name
            passed.append(name)
        assert sql("INSERT INTO wms.physical_shipment_act VALUES(2,1,'{\"execution_mode\":\"wms\",\"lines\":[{\"warehouse\":\"W\"}]}')", check=False).returncode != 0
        passed.append("wrong_shipment_origin_rejected")
        sql("INSERT INTO wms.physical_shipment_act VALUES(2,1,'{\"execution_mode\":\"document\",\"lines\":[{\"warehouse\":\"W\"}]}')")
        passed.append("document_origin_accepted")
        sql("INSERT INTO wms.physical_shipment_act VALUES(1,1,'{\"execution_mode\":\"wms\",\"lines\":[{\"warehouse\":\"W\"}]}')")
        passed.append("legacy_wms_origin_accepted")
    else:
        with ThreadPoolExecutor(max_workers=1) as executor:
            switch = executor.submit(sql, "SET application_name='mode_switch'; BEGIN; SELECT id FROM accounting.organization WHERE id=1 FOR UPDATE; SELECT pg_sleep(3); UPDATE wms.warehouse_directory SET wms_enabled=true WHERE id=1; COMMIT;")
            for attempt in range(30):
                sleeping = sql("SELECT count(*) FROM pg_stat_activity WHERE application_name='mode_switch' AND wait_event='PgSleep'").stdout.strip()
                if sleeping == "1":
                    break
                time.sleep(.1)
            else:
                raise RuntimeError("Concurrent switch did not acquire its book lock")
            stale = sql("INSERT INTO wms.invoice_reservation VALUES(2,1,'{\"allocations\":[{\"warehouse\":\"W\"}]}','{\"W\":false}')", check=False)
            switch.result()
            assert stale.returncode != 0 and "mode is unknown or changed" in stale.stderr
            assert sql("SELECT count(*) FROM wms.invoice_reservation WHERE document_id=2").stdout.strip()=="0"
            passed.append("concurrent_switch_rejects_stale_reservation_after_book_lock")

finally:
    if container:
        label = command(["docker", "inspect", "--format", '{{index .Config.Labels "crm.mode-test"}}', container]).stdout.strip()
        if label != OWNER:
            raise RuntimeError("Cleanup refused: ownership mismatch")
        command(["docker", "rm", "-f", container])
print(json.dumps({"passed":len(passed), "checks":passed, "migration_sha256":hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),
    "scope":"new SQL only, synthetic minimal tables", "container_removed":True, "production_changed":False}))
