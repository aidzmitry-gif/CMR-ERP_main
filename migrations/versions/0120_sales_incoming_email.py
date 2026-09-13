"""sales: immutable incoming receipts and outgoing reply snapshots.

0120 is reserved for CRM-SEND-001. SEND-first ordering was coordinated with the
CP owner: this follows 0116; their unpublished 0117 will subsequently follow 0120.
"""

import sqlalchemy as sa
from alembic import op

revision = "0120"
down_revision = "0116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incoming_email",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("mailbox", sa.String(254), nullable=False),
        sa.Column("uidvalidity", sa.BigInteger(), nullable=False),
        sa.Column("uid", sa.BigInteger(), nullable=False),
        sa.Column("raw", sa.LargeBinary(), nullable=False),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("message_date", sa.DateTime(), nullable=True),
        sa.Column("sender", sa.String(254), nullable=True),
        sa.Column("to", sa.JSON(), nullable=False),
        sa.Column("cc", sa.JSON(), nullable=False),
        sa.Column("subject", sa.String(250), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("message_id", sa.String(255), nullable=True),
        sa.Column("in_reply_to", sa.JSON(), nullable=False),
        sa.Column("references", sa.JSON(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("deal_id", sa.Integer(), sa.ForeignKey("sales.deal.id"), nullable=True),
        sa.Column("routing_status", sa.String(24), nullable=False),
        sa.Column("routing_reason", sa.String(64), nullable=False),
        sa.UniqueConstraint("mailbox", "uidvalidity", "uid", name="uq_incoming_email_identity"),
        sa.CheckConstraint("uidvalidity > 0 AND uid > 0", name="incoming_email_positive_uid"),
        schema="sales",
    )
    op.create_index("ix_incoming_email_inbox", "incoming_email", ["deal_id", "received_at"], schema="sales")
    op.add_column("outgoing_email", sa.Column("reply_to_receipt_id", sa.String(64), nullable=True), schema="sales")
    op.create_foreign_key(
        "fk_outgoing_email_reply_receipt", "outgoing_email", "incoming_email",
        ["reply_to_receipt_id"], ["id"], source_schema="sales", referent_schema="sales",
    )
    # All payload fields are immutable, including extracted metadata and receipt
    # identity. Only assignment state is mutable and is audited by its route.
    op.execute("""
        CREATE FUNCTION sales.guard_incoming_email_snapshot() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.raw IS DISTINCT FROM OLD.raw OR ROW(
                NEW.id, NEW.mailbox, NEW.uidvalidity, NEW.uid, NEW.raw_sha256,
                NEW.received_at, NEW.message_date, NEW.sender, NEW."to"::jsonb,
                NEW.cc::jsonb, NEW.subject, NEW.body_text, NEW.headers::jsonb,
                NEW.message_id, NEW.in_reply_to::jsonb, NEW."references"::jsonb,
                NEW.attachments::jsonb
            ) IS DISTINCT FROM ROW(
                OLD.id, OLD.mailbox, OLD.uidvalidity, OLD.uid, OLD.raw_sha256,
                OLD.received_at, OLD.message_date, OLD.sender, OLD."to"::jsonb,
                OLD.cc::jsonb, OLD.subject, OLD.body_text, OLD.headers::jsonb,
                OLD.message_id, OLD.in_reply_to::jsonb, OLD."references"::jsonb,
                OLD.attachments::jsonb
            ) THEN
                RAISE EXCEPTION 'incoming email snapshot is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER incoming_email_snapshot_immutable BEFORE UPDATE ON sales.incoming_email
        FOR EACH ROW EXECUTE FUNCTION sales.guard_incoming_email_snapshot()
    """)
    # Keep every existing queue/confirmation/recovery transition writable.
    op.execute("""
        CREATE FUNCTION sales.guard_outgoing_email_snapshot() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.mime IS DISTINCT FROM OLD.mime OR ROW(
                NEW.id, NEW.deal_id, NEW.request_key, NEW.request_hash, NEW.created_by,
                NEW.created_at, NEW.sender, NEW."to"::jsonb, NEW.cc::jsonb,
                NEW.subject, NEW.body, NEW.attachments::jsonb, NEW.mime_sha256,
                NEW.message_id, NEW.reply_to_receipt_id
            ) IS DISTINCT FROM ROW(
                OLD.id, OLD.deal_id, OLD.request_key, OLD.request_hash, OLD.created_by,
                OLD.created_at, OLD.sender, OLD."to"::jsonb, OLD.cc::jsonb,
                OLD.subject, OLD.body, OLD.attachments::jsonb, OLD.mime_sha256,
                OLD.message_id, OLD.reply_to_receipt_id
            ) THEN
                RAISE EXCEPTION 'outgoing email snapshot is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER outgoing_email_snapshot_immutable BEFORE UPDATE ON sales.outgoing_email
        FOR EACH ROW EXECUTE FUNCTION sales.guard_outgoing_email_snapshot()
    """)


def downgrade() -> None:
    # Refuse before any DROP: operational rollback with originals is image-only.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM sales.incoming_email)
                OR EXISTS (SELECT 1 FROM sales.outgoing_email WHERE reply_to_receipt_id IS NOT NULL)
            THEN
                RAISE EXCEPTION 'incoming originals prevent schema downgrade' USING ERRCODE = '23514';
            END IF;
        END $$
    """)
    op.execute("DROP TRIGGER outgoing_email_snapshot_immutable ON sales.outgoing_email")
    op.execute("DROP FUNCTION sales.guard_outgoing_email_snapshot()")
    op.execute("DROP TRIGGER incoming_email_snapshot_immutable ON sales.incoming_email")
    op.execute("DROP FUNCTION sales.guard_incoming_email_snapshot()")
    op.drop_constraint("fk_outgoing_email_reply_receipt", "outgoing_email", schema="sales", type_="foreignkey")
    op.drop_column("outgoing_email", "reply_to_receipt_id", schema="sales")
    op.drop_table("incoming_email", schema="sales")
