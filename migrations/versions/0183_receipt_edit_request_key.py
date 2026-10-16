"""Make procurement receipt draft edits exactly replayable after an uncertain response.

Historical revisions have no request key and remain readable. New edits must
carry an explicit key scoped to their receipt; the unique constraint protects
concurrent delivery in addition to the header row lock.
"""

import sqlalchemy as sa
from alembic import op

revision = "0183"
down_revision = "0182"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("receipt_revision", sa.Column("request_key", sa.String(length=160), nullable=True),
                  schema="procurement")
    op.create_unique_constraint("uq_receipt_revision_request", "receipt_revision",
                                ["receipt_id", "request_key"], schema="procurement")


def downgrade():
    raise RuntimeError("Receipt revision request keys cannot be dropped without losing replay evidence")
