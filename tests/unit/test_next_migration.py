import ast
from collections import Counter
from io import StringIO
from pathlib import Path

from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql

from scripts import coordination_hook, next_migration

ROOT = Path(__file__).resolve().parents[2]


def test_head_prefers_real_head_over_stale_reservation():
    assert next_migration._head(
        {"0090", "0105", "0106"},
        {"0090", "0105"},
        [(90, "0090")],
    ) == "0106"


def test_head_uses_newer_reservation_after_real_head():
    assert next_migration._head(
        {"0105", "0106"},
        {"0105"},
        [(107, "0106")],
    ) == "0107"


def test_head_uses_nonnumeric_alembic_tip_when_no_numeric_tip_exists():
    assert next_migration._head({"base", "merge_tip"}, {"base"}, []) == "merge_tip"


def test_scan_tracks_tuple_list_and_none_down_revisions(tmp_path, monkeypatch):
    migrations = tmp_path / "versions"
    migrations.mkdir()
    (migrations / "0128_base.py").write_text('revision = "0128"\ndown_revision = None\n', encoding="utf-8")
    (migrations / "0129_crm.py").write_text('revision = "0129"\ndown_revision = "0128"\n', encoding="utf-8")
    (migrations / "0132_accounting.py").write_text('revision = "0132"\ndown_revision = ["0130", "0131"]\n', encoding="utf-8")
    (migrations / "0133_merge.py").write_text('revision = "0133"\ndown_revision = ("0129", "0132")\n', encoding="utf-8")
    (migrations / "0137_mapping.py").write_text('revision = "0137"\ndown_revision = "0133"\n', encoding="utf-8")
    monkeypatch.setattr(next_migration, "MIGR", migrations)

    revs, downs = next_migration._scan()

    assert revs == {"0128", "0129", "0132", "0133", "0137"}
    assert downs == {"0128", "0129", "0130", "0131", "0132", "0133"}
    assert next_migration._head(revs, downs, []) == "0137"


def test_coordination_hook_accepts_the_same_merge_history(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations" / "versions"
    migrations.mkdir(parents=True)
    (migrations / "0128_base.py").write_text('revision = "0128"\ndown_revision = None\n', encoding="utf-8")
    (migrations / "0129_crm.py").write_text('revision = "0129"\ndown_revision = "0128"\n', encoding="utf-8")
    (migrations / "0132_accounting.py").write_text('revision = "0132"\ndown_revision = ["0130", "0131"]\n', encoding="utf-8")
    (migrations / "0133_merge.py").write_text('revision = "0133"\ndown_revision = ("0129", "0132")\n', encoding="utf-8")
    (migrations / "0137_mapping.py").write_text('revision = "0137"\ndown_revision = "0133"\n', encoding="utf-8")
    monkeypatch.setattr(coordination_hook, "_git", lambda *_args: str(tmp_path))

    assert coordination_hook._alembic_heads() == ["0137"]


def test_deal_task_source_ref_revision_remains_reversible():
    config = Config(str(ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision_id = "crm_live_deal_task_source_ref_01"
    revision = scripts.get_revision(revision_id)
    assert revision is not None
    assert revision.down_revision == "crm_live_timeline_attach_01"

    module = scripts.get_revision(revision_id).module

    upgrade_output = StringIO()
    upgrade_context = MigrationContext.configure(
        dialect=postgresql.dialect(),
        opts={"as_sql": True, "output_buffer": upgrade_output},
    )
    with Operations.context(upgrade_context):
        module.upgrade()
    upgrade_sql = upgrade_output.getvalue()
    assert "ALTER TABLE sales.deal_task ADD COLUMN source_ref VARCHAR(128)" in upgrade_sql
    assert "ADD CONSTRAINT uq_deal_task_source_ref UNIQUE (source_ref)" in upgrade_sql
    assert "source_ref VARCHAR(128) NOT NULL" not in upgrade_sql

    downgrade_output = StringIO()
    downgrade_context = MigrationContext.configure(
        dialect=postgresql.dialect(),
        opts={"as_sql": True, "output_buffer": downgrade_output},
    )
    with Operations.context(downgrade_context):
        module.downgrade()
    downgrade_sql = downgrade_output.getvalue()
    assert "DROP CONSTRAINT uq_deal_task_source_ref" in downgrade_sql
    assert "DROP COLUMN source_ref" in downgrade_sql


def test_release_head_preserves_the_joint_revision_and_exact_frozen_parents():
    config = Config(str(ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    definitions = []
    parents = set()
    for path in (ROOT / "migrations" / "versions").glob("*.py"):
        values = {}
        for node in ast.parse(path.read_text(encoding="utf-8-sig")).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in {"revision", "down_revision"}:
                    values[node.targets[0].id] = ast.literal_eval(node.value)
        definitions.append(values["revision"])
        down = values["down_revision"]
        parents.update(down if isinstance(down, (tuple, list)) else [down] if down else [])
    duplicates = {revision for revision, count in Counter(definitions).items() if count > 1}
    assert not duplicates, f"Duplicate migration revisions: {sorted(duplicates)}"
    assert not parents - set(definitions), f"Missing migration parents: {sorted(parents - set(definitions))}"
    assert {revision.revision for revision in scripts.walk_revisions()} == set(definitions)
    # The additive 0200 correction follows 0199; all frozen release and
    # historical joint parents remain exact ancestors of the single head.
    assert scripts.get_heads() == ["0200"]
    assert scripts.get_revision("0200").down_revision == "0199"
    assert scripts.get_revision("0199").down_revision == "0198"
    assert scripts.get_revision("0198").down_revision == "0194"
    assert "crm_rel_001_auto_posting_01" in {
        revision.revision for revision in scripts.walk_revisions(head="0194")
    }
    assert scripts.get_revision("crm_rel_001_auto_posting_01").down_revision == "crm_rel_001_native_docs_01"
    assert scripts.get_revision("crm_rel_001_native_docs_01").down_revision == "crm_rel_001_native_catalog_01"
    assert scripts.get_revision("crm_rel_001_native_catalog_01").down_revision == "crm_rel_001_output_source_01"
    assert scripts.get_revision("crm_rel_001_output_source_01").down_revision == "crm_rel_001_finished_goods_01"
    assert scripts.get_revision("crm_rel_001_finished_goods_01").down_revision == "crm_rel_001_joint_01"
    joint = scripts.get_revision("crm_rel_001_joint_01")
    assert joint.down_revision == ("0192", "crm_live_deal_task_fidelity_01")
    for operation in (joint.module.upgrade, joint.module.downgrade):
        output = StringIO()
        context = MigrationContext.configure(
            dialect=postgresql.dialect(),
            opts={"as_sql": True, "output_buffer": output},
        )
        with Operations.context(context):
            operation()
        assert output.getvalue() == ""


def test_automatic_posting_migration_is_add_only_and_preserves_configured_history():
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    module = scripts.get_revision("crm_rel_001_auto_posting_01").module
    outputs = []
    for operation in (module.upgrade, module.downgrade):
        output = StringIO()
        context = MigrationContext.configure(dialect=postgresql.dialect(),
            opts={"as_sql": True, "output_buffer": output})
        with Operations.context(context):
            operation()
        outputs.append(output.getvalue())
    assert outputs[0].strip() == "ALTER TABLE accounting.policy ADD COLUMN document_posting JSONB;"
    assert "UPDATE" not in outputs[0] and "DEFAULT" not in outputs[0]
    assert "WHERE document_posting IS NOT NULL" in outputs[1]
    assert outputs[1].index("RAISE EXCEPTION") < outputs[1].index("DROP COLUMN document_posting")


def test_deal_task_fidelity_revision_remains_reversible_with_its_data_loss_guard():
    config = Config(str(ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision_id = "crm_live_deal_task_fidelity_01"
    revision = scripts.get_revision(revision_id)
    assert revision is not None
    assert revision.down_revision == "crm_live_deal_task_source_ref_01"
    module = revision.module

    upgrade_output = StringIO()
    upgrade_context = MigrationContext.configure(
        dialect=postgresql.dialect(),
        opts={"as_sql": True, "output_buffer": upgrade_output},
    )
    with Operations.context(upgrade_context):
        module.upgrade()
    upgrade_sql = upgrade_output.getvalue()
    assert "ALTER TABLE sales.deal_task ALTER COLUMN deal_id DROP NOT NULL" in upgrade_sql
    assert "ADD COLUMN description TEXT" in upgrade_sql
    assert "ADD COLUMN description_in_bbcode BOOLEAN" in upgrade_sql
    assert "ADD COLUMN source_responsible_id VARCHAR(64)" in upgrade_sql
    assert "ADD COLUMN source_status_code VARCHAR(16)" in upgrade_sql
    assert "CREATE TABLE sales.deal_task_crm_link" in upgrade_sql
    assert "raw_binding TEXT" in upgrade_sql
    assert "UNIQUE (task_id, ordinal)" in upgrade_sql
    assert "INSERT INTO sales.deal_task_crm_link" in upgrade_sql
    assert "SELECT id, 0, NULL, NULL, NULL, deal_id" in upgrade_sql
    assert "WHERE deal_id IS NOT NULL" in upgrade_sql

    downgrade_output = StringIO()
    downgrade_context = MigrationContext.configure(
        dialect=postgresql.dialect(),
        opts={"as_sql": True, "output_buffer": downgrade_output},
    )
    with Operations.context(downgrade_context):
        module.downgrade()
    downgrade_sql = downgrade_output.getvalue()
    assert "LOCK TABLE sales.deal_task, sales.deal_task_crm_link IN ACCESS EXCLUSIVE MODE" in downgrade_sql
    assert "RAISE EXCEPTION 'Cannot downgrade: deal task fidelity data is not representable'" in downgrade_sql
    assert "COUNT(link.id) <> 1" in downgrade_sql
    assert "link.raw_binding IS NOT NULL" in downgrade_sql
    assert "link.deal_id IS DISTINCT FROM task.deal_id" in downgrade_sql
    assert downgrade_sql.index("LOCK TABLE sales.deal_task") < downgrade_sql.index("DO $$")
    assert downgrade_sql.index("DO $$") < downgrade_sql.index(
        "DROP TABLE sales.deal_task_crm_link"
    )
    assert "DROP COLUMN description" in downgrade_sql
    assert "ALTER TABLE sales.deal_task ALTER COLUMN deal_id SET NOT NULL" in downgrade_sql


def test_finished_goods_migration_preserves_frozen_contract_and_blocks_lossy_downgrade():
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    module = scripts.get_revision("crm_rel_001_finished_goods_01").module
    sql = module.definitions()
    frozen = module.frozen("0130_accounting_ledger.py")
    assert "validate_shipment_output_layer" not in frozen
    assert "accounting.financial_sha(posting) IS DISTINCT FROM receipt.digest" in sql
    assert "basis->>'basis_digest' IS DISTINCT FROM receipt.basis_digest" in sql
    assert "financial_sha(basis)" not in module.HELPER
    assert "r.registration_token<excluded_entry" in sql
    assert "Shipment output WIP source basis is stale" in sql
    assert "bucket.account ~ '^41([.]|$)' OR e.id<r.anchor_entry_id" in sql
    assert "Unverified output layer movement" not in sql
    assert "Shipment inventory and expense ledger coverage differs" in sql
    assert "Shipment revenue and VAT ledger coverage differs" in sql
    assert "output_cost_revision_evidence(" not in sql
    output = StringIO()
    context = MigrationContext.configure(dialect=postgresql.dialect(),
                                         opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        module.downgrade()
    assert "Cannot downgrade finished-goods shipment history" in output.getvalue()
    assert "DELETE" not in output.getvalue()


def test_output_source_migration_preserves_generic_guard_and_existing_production_guard():
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    module = scripts.get_revision("crm_rel_001_output_source_01").module
    sql = module.definitions()
    old = module.frozen_guard()
    new = sql[sql.index("CREATE OR REPLACE FUNCTION accounting.guard_source_control("):]
    branch = ("  IF NEW.entry_id IS NOT NULL AND NEW.source LIKE 'production:output:%'\n"
              "     AND EXISTS (SELECT 1 FROM accounting.entry e WHERE e.id=NEW.entry_id AND e.source<>NEW.source) THEN\n"
              "    PERFORM accounting.validate_output_source_completion(NEW.organization_id,NEW.source,NEW.version,NEW.month,NEW.entry_id);\n"
              "  ELSIF NEW.entry_id IS NOT NULL AND NOT EXISTS (")
    assert new.replace(branch, "  IF NEW.entry_id IS NOT NULL AND NOT EXISTS (") == old
    assert "production.guard_output_source_control" not in sql
    assert "validate_shipment_output_layer(org,target_entry,debit.id,debit.account_code" in sql
    assert "ids IS DISTINCT FROM native_ids OR ids IS DISTINCT FROM basis_ids" in sql
    assert "complete_output_receipt_sources" in sql
    assert "Cannot downgrade output-source completion with linked production history" in __import__("inspect").getsource(module.downgrade)

    assert "AND e.organization_id=NEW.organization_id AND e.source=NEW.source" in module.VALIDATOR
    assert "AND e.source_version=NEW.version AND to_char(e.posting_date,'YYYY-MM')=NEW.month" in module.VALIDATOR
