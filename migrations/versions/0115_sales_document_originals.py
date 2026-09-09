"""Immutable document originals and packages; no legacy backfill."""
import sqlalchemy as sa
from alembic import op

revision = "0115"
down_revision = "0114"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('deal_document', sa.Column('version', sa.Integer(), nullable=False, server_default='1'), schema='sales')
    for name in ('supersedes_id', 'superseded_by_id'):
        op.add_column('deal_document', sa.Column(name, sa.Integer(), nullable=True), schema='sales')
        op.create_foreign_key(f'fk_document_{name}', 'deal_document', 'deal_document', [name], ['id'], source_schema='sales', referent_schema='sales')
    for name, type_ in (
        ('replacement_reason', sa.String(500)), ('request_key', sa.String(64)),
        ('request_hash', sa.String(64)), ('snapshot_json', sa.JSON()),
        ('original_html', sa.Text()), ('content_sha256', sa.String(64)),
        ('issued_at', sa.DateTime()), ('issued_by', sa.String(128)),
    ):
        op.add_column('deal_document', sa.Column(name, type_, nullable=True), schema='sales')
    op.create_unique_constraint('uq_document_request_key', 'deal_document', ['request_key'], schema='sales')
    op.create_table('document_package',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('deal_id', sa.Integer(), sa.ForeignKey('sales.deal.id'), nullable=False),
        sa.Column('invoice_id', sa.Integer(), sa.ForeignKey('sales.deal_document.id'), nullable=False),
        sa.Column('contract_id', sa.Integer(), sa.ForeignKey('sales.deal_document.id'), nullable=False),
        sa.Column('original_html', sa.Text(), nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('created_by', sa.String(128), nullable=False),
        sa.UniqueConstraint('invoice_id', 'contract_id', name='uq_document_package_versions'),
        schema='sales',
    )
    install_guards()


def install_guards():
    op.execute("""
    CREATE FUNCTION sales.protect_document_original() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        IF OLD.original_html IS NOT NULL OR OLD.status IN ('posted','paid','cancelled') THEN
          RAISE EXCEPTION 'Historical document cannot be deleted';
        END IF;
        RETURN OLD;
      END IF;
      IF OLD.original_html IS NOT NULL AND
         (to_jsonb(NEW) - ARRAY['status','onec_ref','posted_at','reserve_status','reserved_at',
          'reminded_at','cancelled_at','issued_at','issued_by','superseded_by_id']) IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['status','onec_ref','posted_at','reserve_status','reserved_at',
          'reminded_at','cancelled_at','issued_at','issued_by','superseded_by_id']) THEN
        RAISE EXCEPTION 'Saved original is immutable; create a new version';
      END IF;
      IF OLD.issued_at IS NOT NULL AND ROW(NEW.issued_at,NEW.issued_by) IS DISTINCT FROM ROW(OLD.issued_at,OLD.issued_by) THEN
        RAISE EXCEPTION 'Issue identity is immutable';
      END IF;
      IF OLD.superseded_by_id IS NOT NULL AND NEW.superseded_by_id IS DISTINCT FROM OLD.superseded_by_id THEN
        RAISE EXCEPTION 'Replacement history is immutable';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_document_original BEFORE UPDATE OR DELETE ON sales.deal_document
      FOR EACH ROW EXECUTE FUNCTION sales.protect_document_original();
    CREATE FUNCTION sales.protect_document_package() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Prepared package is immutable'; END $$;
    CREATE TRIGGER immutable_document_package BEFORE UPDATE OR DELETE ON sales.document_package
      FOR EACH ROW EXECUTE FUNCTION sales.protect_document_package();
    """)


def downgrade():
    # Downgrade would discard the only original. Require a separately reviewed export/migration.
    raise RuntimeError('No automatic destructive downgrade: export and verify all originals first')
