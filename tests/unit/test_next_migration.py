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


def test_deal_task_fidelity_revision_is_single_head_and_reversible():
    config = Config(str(ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision_id = "crm_live_deal_task_fidelity_01"
    assert scripts.get_heads() == [revision_id]
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
