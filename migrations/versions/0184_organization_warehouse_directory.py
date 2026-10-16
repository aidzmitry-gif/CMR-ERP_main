"""Register physical warehouses by legal entity without adopting legacy names.

No existing stock movement or receipt is assigned an owner by this migration.
"""

import sqlalchemy as sa
from alembic import op

revision = "0184"
down_revision = "0183"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "warehouse_directory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("accounting.organization.id"), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("organization_id > 0", name="wms_warehouse_directory_org_positive"),
        sa.UniqueConstraint("organization_id", "name", name="uq_wms_warehouse_directory_name"),
        schema="wms",
    )
    op.create_index("ix_wms_warehouse_directory_organization_id", "warehouse_directory",
                    ["organization_id"], schema="wms")
    op.execute("""
        CREATE FUNCTION wms.guard_warehouse_directory_identity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' OR NEW.id IS DISTINCT FROM OLD.id
             OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
             OR NEW.name IS DISTINCT FROM OLD.name
             OR NEW.created_by IS DISTINCT FROM OLD.created_by
             OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'Warehouse identity cannot be changed or deleted';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER guard_warehouse_directory_identity
        BEFORE UPDATE OR DELETE ON wms.warehouse_directory
        FOR EACH ROW EXECUTE FUNCTION wms.guard_warehouse_directory_identity()
    """)
    op.execute("""
        CREATE FUNCTION wms.guard_primary_receipt_warehouse() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE warehouse_id_text text;
        BEGIN
          PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'Primary receipt organization does not exist';
          END IF;
          warehouse_id_text := NEW.command->>'warehouse_id';
          IF jsonb_typeof(NEW.command::jsonb->'warehouse_id') IS DISTINCT FROM 'number'
             OR warehouse_id_text IS NULL OR length(warehouse_id_text) > 10
             OR warehouse_id_text !~ '^[1-9][0-9]*$' THEN
            RAISE EXCEPTION 'Primary receipt warehouse catalogue ID is required';
          END IF;
          PERFORM 1 FROM wms.warehouse_directory
            WHERE id = warehouse_id_text::integer AND organization_id = NEW.organization_id
              AND name = NEW.command->>'warehouse' AND is_active
            FOR SHARE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'Primary receipt warehouse catalogue binding differs from the command';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER a_guard_primary_receipt_warehouse
        BEFORE INSERT ON wms.primary_receipt_binding
        FOR EACH ROW EXECUTE FUNCTION wms.guard_primary_receipt_warehouse()
    """)


def downgrade():
    raise RuntimeError("Warehouse identities cannot be dropped without reviewing linked documents")
