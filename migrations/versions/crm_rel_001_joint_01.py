"""Join the frozen accounting and CRM task fidelity histories.

Both parents must execute before this marker. The merge changes no schema or
data; restoring a release still requires its independently verified restore path.
"""

revision = "crm_rel_001_joint_01"
down_revision = ("0192", "crm_live_deal_task_fidelity_01")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
