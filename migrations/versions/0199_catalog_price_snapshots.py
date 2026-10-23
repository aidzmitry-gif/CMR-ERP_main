"""Retain reference prices independently of warehouse stock."""
import sqlalchemy as sa
from alembic import op

revision = "0199"
down_revision = "0198"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.create_table(
        "catalog_price_snapshot",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("content_sha", sa.String(64), nullable=False),
        sa.Column("selected_kind", sa.String(36), nullable=False),
        sa.Column("kind_name", sa.String(255), nullable=False),
        sa.Column("price_includes_vat", sa.Boolean(), nullable=False),
        sa.Column("source_as_of", sa.DateTime(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("prices_sha", sa.String(64), nullable=False),
        sa.Column("kinds_sha", sa.String(64), nullable=False),
        sa.Column("currencies_sha", sa.String(64), nullable=False),
        sa.Column("prices_text", sa.Text(), nullable=False),
        sa.Column("kinds_text", sa.Text(), nullable=False),
        sa.Column("currencies_text", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("response_complete", sa.Boolean(), nullable=False),
        sa.Column("full_coverage", sa.Boolean(), nullable=False),
        sa.Column("activity_verified", sa.Boolean(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.CheckConstraint("row_count >= 0 AND row_count <= 10000", name="catalog_price_count"),
        sa.CheckConstraint("response_complete AND NOT full_coverage AND NOT activity_verified",
                           name="catalog_price_reference_proof"),
        schema="integrations",
    )
    op.create_index("uq_catalog_price_current", "catalog_price_snapshot", ["is_current"],
                    unique=True, schema="integrations", postgresql_where=sa.text("is_current"))
    op.create_table(
        "catalog_price_observation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey(
            "integrations.catalog_price_snapshot.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_guid", sa.String(36), nullable=False),
        sa.Column("characteristic_guid", sa.String(36), nullable=False),
        sa.Column("kind_guid", sa.String(36), nullable=False),
        sa.Column("package_guid", sa.String(36), nullable=False),
        sa.Column("currency_guid", sa.String(36), nullable=False),
        sa.Column("currency_code", sa.String(32)),
        sa.Column("effective_at", sa.DateTime(), nullable=False),
        sa.Column("price", sa.Numeric(28, 10), nullable=False),
        sa.Column("price_text", sa.String(80), nullable=False),
        sa.Column("sku_id", sa.Integer(), sa.ForeignKey("public.sku.id", ondelete="RESTRICT")),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey(
            "public.catalog_source_identity.id", ondelete="RESTRICT")),
        sa.Column("identity_revision", sa.Integer()),
        sa.Column("identity_target_sha", sa.String(64)),
        sa.Column("mapping_status", sa.String(16), nullable=False),
        sa.Column("mapping_reason", sa.String(64)),
        sa.UniqueConstraint("snapshot_id", "product_guid", "characteristic_guid", "kind_guid",
                            "package_guid", "currency_guid", name="uq_catalog_price_dimensions"),
        sa.CheckConstraint("price >= 0 AND price < 1000000000000000000",
                           name="catalog_price_amount"),
        sa.CheckConstraint("mapping_status IN ('mapped','held','unmapped')",
                           name="catalog_price_mapping_status"),
        sa.CheckConstraint("mapping_status <> 'mapped' OR (sku_id IS NOT NULL AND "
                           "identity_id IS NOT NULL AND identity_revision IS NOT NULL AND "
                           "identity_revision > 0 AND "
                           "identity_target_sha IS NOT NULL)", name="catalog_price_mapped_target"),
        schema="integrations",
    )
    op.create_index("ix_integrations_catalog_price_observation_snapshot_id",
                    "catalog_price_observation", ["snapshot_id"], schema="integrations")


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    # Refuse before the first DDL statement; an image rollback cannot erase history.
    # Lock before EXISTS so a concurrent import cannot commit between check and DROP.
    op.get_bind().execute(sa.text(
        "LOCK TABLE integrations.catalog_price_snapshot, "
        "integrations.catalog_price_observation IN ACCESS EXCLUSIVE MODE"
    ))
    retained = op.get_bind().scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM integrations.catalog_price_snapshot) "
        "OR EXISTS (SELECT 1 FROM integrations.catalog_price_observation)"
    ))
    if retained:
        raise RuntimeError("Cannot remove retained source-price history")
    op.drop_table("catalog_price_observation", schema="integrations")
    op.drop_table("catalog_price_snapshot", schema="integrations")
