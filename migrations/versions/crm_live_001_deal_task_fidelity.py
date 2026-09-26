"""Preserve Bitrix task fields and ordered CRM bindings."""

import sqlalchemy as sa
from alembic import op


revision = "crm_live_deal_task_fidelity_01"
down_revision = "crm_live_deal_task_source_ref_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "deal_task",
        "deal_id",
        existing_type=sa.Integer(),
        nullable=True,
        schema="sales",
    )
    op.add_column("deal_task", sa.Column("description", sa.Text(), nullable=True), schema="sales")
    op.add_column(
        "deal_task",
        sa.Column("description_in_bbcode", sa.Boolean(), nullable=True),
        schema="sales",
    )
    op.add_column(
        "deal_task",
        sa.Column("source_responsible_id", sa.String(64), nullable=True),
        schema="sales",
    )
    op.add_column(
        "deal_task",
        sa.Column("source_status_code", sa.String(16), nullable=True),
        schema="sales",
    )
    op.create_table(
        "deal_task_crm_link",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("sales.deal_task.id"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("raw_binding", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.String(32), nullable=True),
        sa.Column("source_id", sa.String(64), nullable=True),
        sa.Column(
            "deal_id",
            sa.Integer(),
            sa.ForeignKey("sales.deal.id"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "task_id", "ordinal", name="uq_deal_task_crm_link_task_ordinal"
        ),
        schema="sales",
    )
    op.execute(
        """
        INSERT INTO sales.deal_task_crm_link
            (task_id, ordinal, raw_binding, entity_type, source_id, deal_id)
        SELECT id, 0, NULL, NULL, NULL, deal_id
        FROM sales.deal_task
        WHERE deal_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    # The old table can represent exactly one deal per task and has no source detail.
    # Hold off concurrent writers until the guard and DDL commit together.
    op.execute(
        "LOCK TABLE sales.deal_task, sales.deal_task_crm_link IN ACCESS EXCLUSIVE MODE"
    )
    # Guard before DDL so rollback never silently drops unbound/multiple/raw bindings.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM sales.deal_task
                WHERE description IS NOT NULL
                   OR description_in_bbcode IS NOT NULL
                   OR source_responsible_id IS NOT NULL
                   OR source_status_code IS NOT NULL
            ) OR EXISTS (
                SELECT task.id
                FROM sales.deal_task AS task
                LEFT JOIN sales.deal_task_crm_link AS link
                    ON link.task_id = task.id
                GROUP BY task.id, task.deal_id
                HAVING COUNT(link.id) <> 1
                    OR COUNT(link.id) FILTER (
                        WHERE link.raw_binding IS NOT NULL
                           OR link.entity_type IS NOT NULL
                           OR link.source_id IS NOT NULL
                           OR link.deal_id IS NULL
                           OR link.deal_id IS DISTINCT FROM task.deal_id
                    ) <> 0
            ) THEN
                RAISE EXCEPTION 'Cannot downgrade: deal task fidelity data is not representable';
            END IF;
        END $$;
        """
    )
    op.drop_table("deal_task_crm_link", schema="sales")
    op.drop_column("deal_task", "source_status_code", schema="sales")
    op.drop_column("deal_task", "source_responsible_id", schema="sales")
    op.drop_column("deal_task", "description_in_bbcode", schema="sales")
    op.drop_column("deal_task", "description", schema="sales")
    op.alter_column(
        "deal_task",
        "deal_id",
        existing_type=sa.Integer(),
        nullable=False,
        schema="sales",
    )
