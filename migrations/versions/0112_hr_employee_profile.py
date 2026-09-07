"""Private employee self-service profile. Number reserved by operator."""
import sqlalchemy as sa
from alembic import op

revision = "0112"
down_revision = "0111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employee_profile",
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr.employee.id"), primary_key=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("phone", sa.String(40), nullable=False, server_default=""),
        sa.Column("city", sa.String(128), nullable=False, server_default=""),
        sa.Column("education", sa.String(500), nullable=False, server_default=""),
        sa.Column("children_birth_dates", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="hr",
    )


def downgrade() -> None:
    op.drop_table("employee_profile", schema="hr")
