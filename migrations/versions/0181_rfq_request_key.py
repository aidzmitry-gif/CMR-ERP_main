"""Give new request-owned RFQs a durable idempotency key.

Old RFQs remain without a key or inferred legal entity. Their request ownership
must be reconciled before they can appear in an organization-scoped view.
"""

import sqlalchemy as sa
from alembic import op

revision = "0181"
down_revision = "0180"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("rfq", sa.Column("request_key", sa.String(length=36), nullable=True), schema="procurement")
    op.create_unique_constraint("uq_rfq_request_key", "rfq", ["request_key"], schema="procurement")
    op.add_column("rfq_bid", sa.Column("bid_key", sa.String(length=36), nullable=True), schema="procurement")
    op.create_unique_constraint("uq_rfq_bid_key", "rfq_bid", ["bid_key"], schema="procurement")
    op.create_table("rfq_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("rfq_id", sa.Integer(), sa.ForeignKey("procurement.rfq.id"), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="procurement")
    op.create_index("ix_rfq_history_organization_id", "rfq_history", ["organization_id"], schema="procurement")
    op.create_index("ix_rfq_history_rfq_id", "rfq_history", ["rfq_id"], schema="procurement")
    op.execute("""CREATE FUNCTION procurement.reject_rfq_history_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION 'RFQ history is immutable';
        END; $$""")
    op.execute("""CREATE TRIGGER reject_rfq_history_mutation
        BEFORE UPDATE OR DELETE ON procurement.rfq_history
        FOR EACH ROW EXECUTE FUNCTION procurement.reject_rfq_history_mutation()""")


def downgrade():
    raise RuntimeError("RFQ history and idempotency keys cannot be dropped without losing audit evidence")
