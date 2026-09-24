"""Require a current MDM supplier for newly committed order-creation packages.

Existing orders and immutable command receipts are unchanged. Rejected command
receipts may still be stored without a selected supplier for safe reconciliation.
"""

from alembic import op

revision = "0180"
down_revision = "0179"
branch_labels = None
depends_on = None


GUARD = r"""CREATE FUNCTION procurement.guard_order_mdm_supplier() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE d jsonb;
BEGIN
  IF NEW.outcome <> 'created' THEN
    RETURN NEW;
  END IF;
  d := NEW.command::jsonb->'document';
  IF d IS NULL OR jsonb_typeof(d->'supplier_id') IS DISTINCT FROM 'number'
    OR (d->>'supplier_id') !~ '^[1-9][0-9]*$'
    OR (d->>'supplier_id')::numeric > 2147483647
    OR jsonb_typeof(d->'supplier_unp') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'Order creation requires a selected supplier';
  END IF;
  PERFORM 1 FROM procurement.supplier s
    JOIN public.counterparty c ON c.id = s.counterparty_id
    WHERE s.id = (d->>'supplier_id')::integer
      AND s.id = (SELECT o.supplier_id FROM procurement.purchase_order o WHERE o.id = NEW.order_id)
      AND s.status = 'active'
      AND c.is_active IS TRUE AND c.merged_into_id IS NULL
      AND s.name = COALESCE(NULLIF(c.legal_name, ''), c.name)
      AND s.unp = COALESCE(c.unp, '')
      AND s.name = d->>'supplier' AND s.unp = d->>'supplier_unp'
    FOR SHARE OF s, c;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Order creation supplier MDM identity changed';
  END IF;
  RETURN NEW;
END;
$$"""


def upgrade():
    op.execute(GUARD)
    op.execute("""CREATE CONSTRAINT TRIGGER guard_order_mdm_supplier
        AFTER INSERT ON procurement.purchase_order_creation
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION procurement.guard_order_mdm_supplier()""")


def downgrade():
    op.execute("DROP TRIGGER guard_order_mdm_supplier ON procurement.purchase_order_creation")
    op.execute("DROP FUNCTION procurement.guard_order_mdm_supplier()")
