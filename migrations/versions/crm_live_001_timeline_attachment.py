"""Store content-addressed files linked to CRM timeline comments."""

import sqlalchemy as sa
from alembic import op

revision = "crm_live_timeline_attach_01"
down_revision = "crm_live_timeline_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_timeline_attachment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "comment_id",
            sa.Integer(),
            sa.ForeignKey("sales.crm_timeline_comment.id"),
            nullable=False,
        ),
        sa.Column("source_ref", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_ref", name="uq_crm_timeline_attachment_source_ref"),
        sa.CheckConstraint(
            "size_bytes >= 0 AND size_bytes <= 2147483648",
            name="ck_crm_timeline_attachment_size",
        ),
        sa.CheckConstraint("length(sha256) = 64", name="ck_crm_timeline_attachment_sha256_length"),
        sa.CheckConstraint("length(source_ref) > 0", name="ck_crm_timeline_attachment_source_ref"),
        schema="sales",
    )
    op.create_index(
        "ix_crm_timeline_attachment_comment",
        "crm_timeline_attachment",
        ["comment_id"],
        schema="sales",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crm_timeline_attachment_comment",
        table_name="crm_timeline_attachment",
        schema="sales",
    )
    op.drop_table("crm_timeline_attachment", schema="sales")
