"""Replay-safe manual message history; local reservation CRM-READY-001 0128."""
import sqlalchemy as sa
from alembic import op

revision = "0128"
down_revision = "0127"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("message", sa.Column("request_key", sa.String(64)), schema="sales")
    op.create_unique_constraint("uq_message_deal_request", "message", ["deal_id", "request_key"], schema="sales")


def downgrade():
    op.drop_constraint("uq_message_deal_request", "message", schema="sales", type_="unique")
    op.drop_column("message", "request_key", schema="sales")
