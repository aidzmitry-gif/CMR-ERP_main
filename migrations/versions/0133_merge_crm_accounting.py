"""Join CRM ownership and Accounting reservation migration histories.

Revision ID: 0133
Revises: 0129, 0132

Both parent branches must execute before this marker. No schema or data
operations are needed in the merge itself.
"""

revision = "0133"
down_revision = ("0129", "0132")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
