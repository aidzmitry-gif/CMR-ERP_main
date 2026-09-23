"""Accept one opening balance package per organization and cutover date."""

from alembic import op

revision = "0169"
down_revision = "0168"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_opening_import_cutover", "opening_import_receipt",
        ["organization_id", "cutover_date"], schema="accounting",
    )


def downgrade():
    op.drop_constraint(
        "uq_opening_import_cutover", "opening_import_receipt",
        schema="accounting", type_="unique",
    )
