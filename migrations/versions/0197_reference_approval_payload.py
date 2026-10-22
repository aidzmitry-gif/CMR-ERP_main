"""Persist exact approval proposals and their write-once application receipts.

Allocated by the shared migration tool. Existing approvals remain NULL. Rollback
refuses any proposal/receipt before DDL; use the verified release restore instead.
"""
import sqlalchemy as sa
from alembic import op

revision = "0197"
down_revision = "0196"
branch_labels = None
depends_on = None


def _locked_connection():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Durable approval migration requires PostgreSQL")
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE approval IN ACCESS EXCLUSIVE MODE")
    return bind


def upgrade() -> None:
    bind = _locked_connection()
    fields = {column["name"] for column in sa.inspect(bind).get_columns("approval")}
    if fields & {"request_payload", "request_sha256", "applied_receipt"}:
        raise RuntimeError("Unexpected durable approval columns; inspect the migration baseline")
    op.add_column("approval", sa.Column("request_payload", sa.JSON(), nullable=True))
    op.add_column("approval", sa.Column("request_sha256", sa.String(64), nullable=True))
    op.add_column("approval", sa.Column("applied_receipt", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = _locked_connection()
    if bind.execute(sa.text("""
        SELECT EXISTS (SELECT 1 FROM approval WHERE request_payload IS NOT NULL
                       OR request_sha256 IS NOT NULL OR applied_receipt IS NOT NULL)
    """)).scalar_one():
        raise RuntimeError("Durable approval evidence cannot be discarded; use the verified release restore")
    for field in ("applied_receipt", "request_sha256", "request_payload"):
        op.drop_column("approval", field)
