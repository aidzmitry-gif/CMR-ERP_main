"""Persist the seller selected in platform Settings; preserve legacy documents."""
import sqlalchemy as sa
from alembic import op

revision = "0204"
down_revision = "0203"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_installation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("organization_unp", sa.String(9), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("command_digest", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="platform_installation_singleton"),
        sa.CheckConstraint("revision > 0", name="platform_installation_revision"),
        sa.CheckConstraint("organization_id > 0", name="platform_installation_organization"),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM platform_installation")).scalar_one():
        raise RuntimeError("Configured installation must be preserved; review configuration recovery before downgrade")
    op.drop_table("platform_installation")
