"""Scope contacts to branches and make source aliases unambiguous; no data deletion."""
import sqlalchemy as sa
from alembic import op

revision = "0119"
down_revision = "0118"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(sa.text(
        "SELECT source, external_ref FROM counterparty_alias "
        "GROUP BY source, external_ref HAVING count(*) > 1 LIMIT 1"
    )).first()
    if duplicates:
        raise RuntimeError("0119: duplicate source aliases require explicit resolution; no records were deleted")
    op.create_unique_constraint("uq_counterparty_alias_source_ref", "counterparty_alias", ["source", "external_ref"])
    op.create_unique_constraint("uq_branch_id_parent", "counterparty_branch", ["id", "legal_entity_id"])
    op.add_column("contact", sa.Column("branch_id", sa.Integer(), nullable=True))
    op.create_index("ix_contact_branch_id", "contact", ["branch_id"])
    op.create_foreign_key("fk_contact_branch_parent", "contact", "counterparty_branch",
                          ["branch_id", "counterparty_id"], ["id", "legal_entity_id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_contact_branch_parent", "contact", "branch_id IS NULL OR counterparty_id IS NOT NULL")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT count(*) FROM contact WHERE branch_id IS NOT NULL")).scalar():
        raise RuntimeError("0119 downgrade would discard branch contact ownership; preserve it before rollback")
    op.drop_constraint("ck_contact_branch_parent", "contact", type_="check")
    op.drop_constraint("fk_contact_branch_parent", "contact", type_="foreignkey")
    op.drop_index("ix_contact_branch_id", table_name="contact")
    op.drop_column("contact", "branch_id")
    op.drop_constraint("uq_branch_id_parent", "counterparty_branch", type_="unique")
    op.drop_constraint("uq_counterparty_alias_source_ref", "counterparty_alias", type_="unique")
