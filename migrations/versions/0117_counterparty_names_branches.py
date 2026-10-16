"""Add separate counterparty names and branch identity without changing legacy links.

Number reserved through the shared registry for CRM-CP-001-v4.
Downgrade refuses to discard branch records or subsequently edited names.
"""
import sqlalchemy as sa
from alembic import op

revision = "0117"
down_revision = "0120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("counterparty", sa.Column("display_name", sa.String(255), nullable=True))
    op.add_column("counterparty", sa.Column("legal_name", sa.String(255), nullable=True))
    op.execute("UPDATE counterparty SET display_name = name")
    op.create_table(
        "counterparty_branch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("legal_entity_id", sa.Integer(), sa.ForeignKey("counterparty.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address", sa.String(1000), nullable=True),
        sa.Column("tax_mode", sa.String(16), server_default="unknown", nullable=False),
        sa.Column("portal_branch_code", sa.String(4), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("provenance", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("tax_mode IN ('unknown', 'shared', 'independent')", name="ck_branch_tax_mode"),
        sa.CheckConstraint("portal_branch_code IS NULL OR length(portal_branch_code) = 4", name="ck_branch_code_length"),
    )
    op.create_index("ix_counterparty_branch_legal_entity_id", "counterparty_branch", ["legal_entity_id"])
    op.create_table(
        "counterparty_branch_alias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("counterparty_branch.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("external_ref", sa.String(255), nullable=False),
        sa.UniqueConstraint("source", "external_ref", name="uq_branch_alias_source_ref"),
    )
    op.create_index("ix_counterparty_branch_alias_branch_id", "counterparty_branch_alias", ["branch_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM counterparty_branch")).scalar():
        raise RuntimeError("0117 downgrade would discard branches; restore a verified pre-upgrade backup instead")
    changed = bind.execute(sa.text(
        "SELECT count(*) FROM counterparty WHERE "
        "(display_name IS NOT NULL AND display_name <> name) OR "
        "legal_name IS NOT NULL"
    )).scalar()
    if changed:
        raise RuntimeError("0117 downgrade would discard edited names; preserve them before rollback")
    op.drop_index("ix_counterparty_branch_alias_branch_id", table_name="counterparty_branch_alias")
    op.drop_table("counterparty_branch_alias")
    op.drop_index("ix_counterparty_branch_legal_entity_id", table_name="counterparty_branch")
    op.drop_table("counterparty_branch")
    op.drop_column("counterparty", "legal_name")
    op.drop_column("counterparty", "display_name")
