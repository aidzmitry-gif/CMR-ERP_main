"""Allow verified login aliases; identity subjects remain unique."""
import sqlalchemy as sa
from alembic import op

revision = "0195"
down_revision = "0194"
branch_labels = None
depends_on = None


def upgrade():
    constraints = [row for row in sa.inspect(op.get_bind()).get_unique_constraints("app_user")
                   if row["column_names"] == ["employee_id"]]
    if len(constraints) != 1 or not constraints[0]["name"]:
        raise RuntimeError("Expected one employee account constraint")
    op.drop_constraint(constraints[0]["name"], "app_user", type_="unique")
    op.create_index("ix_app_user_employee_id", "app_user", ["employee_id"], unique=False)


def downgrade():
    if op.get_bind().execute(sa.text("""
        SELECT 1 FROM app_user WHERE employee_id IS NOT NULL
        GROUP BY employee_id HAVING count(*) > 1 LIMIT 1
    """)).first():
        raise RuntimeError("Resolve login aliases before restoring one-account constraint")
    op.drop_index("ix_app_user_employee_id", table_name="app_user")
    op.create_unique_constraint(op.f("uq_app_user_employee_id"), "app_user", ["employee_id"])
