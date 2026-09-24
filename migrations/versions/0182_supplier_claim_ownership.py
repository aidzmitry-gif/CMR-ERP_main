"""Record explicit company ownership for new supplier claims.

Historical claims, including production scraps without a legal entity, remain
unassigned. Ownership must not be inferred from order text or supplier name.
"""

import sqlalchemy as sa
from alembic import op

revision = "0182"
down_revision = "0181"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "claim_ownership",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("procurement.supplier_claim.id"), nullable=False),
        sa.Column("claim_key", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("procurement.purchase_order.id"), nullable=True),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column("command", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.String(length=1000), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("claim_id", name="uq_claim_ownership_claim"),
        sa.UniqueConstraint("claim_key", name="uq_claim_ownership_key"),
        schema="procurement",
    )
    op.create_index("ix_claim_ownership_organization_id", "claim_ownership", ["organization_id"], schema="procurement")
    op.execute("""CREATE FUNCTION procurement.reject_claim_ownership_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION 'Claim ownership is immutable';
        END; $$""")
    op.execute("""CREATE TRIGGER reject_claim_ownership_mutation
        BEFORE UPDATE OR DELETE ON procurement.claim_ownership
        FOR EACH ROW EXECUTE FUNCTION procurement.reject_claim_ownership_mutation()""")
    op.create_table(
        "claim_edit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("procurement.supplier_claim.id"), nullable=False),
        sa.Column("edit_key", sa.String(length=36), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column("command", sa.JSON(), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=False),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("edit_key", name="uq_claim_edit_key"),
        schema="procurement",
    )
    op.create_index("ix_claim_edit_organization_id", "claim_edit", ["organization_id"], schema="procurement")
    op.execute("""CREATE TRIGGER reject_claim_edit_mutation
        BEFORE UPDATE OR DELETE ON procurement.claim_edit
        FOR EACH ROW EXECUTE FUNCTION procurement.reject_claim_ownership_mutation()""")


def downgrade():
    raise RuntimeError("Claim ownership cannot be dropped without losing legal-entity audit evidence")
