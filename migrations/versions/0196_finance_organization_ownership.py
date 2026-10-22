"""Scope Finance accounts and payments without assigning legacy ownership.

The canonical allocator owns this revision. Unknown legacy owners stay NULL.
Rollback refuses confirmed ownership or duplicate legacy codes before any DDL;
restore the verified release backup instead of silently discarding those facts.
"""
import sqlalchemy as sa
from alembic import op

revision = "0196"
down_revision = "0195"
branch_labels = None
depends_on = None


def _locked_connection():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Finance ownership migration requires PostgreSQL")
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE finance.bank_account, finance.payment IN ACCESS EXCLUSIVE MODE")
    return bind


def upgrade() -> None:
    bind = _locked_connection()
    inspector = sa.inspect(bind)
    for table in ("bank_account", "payment"):
        if "organization_id" in {row["name"] for row in inspector.get_columns(table, schema="finance")}:
            raise RuntimeError("Unexpected Finance ownership columns; inspect the migration baseline")
    uniques = inspector.get_unique_constraints("bank_account", schema="finance")
    if not any(row["name"] == "uq_bank_account_code" and row["column_names"] == ["code"] for row in uniques):
        raise RuntimeError("Expected legacy Finance account code constraint is missing")
    foreign_keys = inspector.get_foreign_keys("payment", schema="finance", postgresql_ignore_search_path=True)
    if not any(row["name"] == "fk_payment_account_id_bank_account"
               and row["constrained_columns"] == ["account_id"]
               and row["referred_table"] == "bank_account"
               and row["referred_schema"] == "finance"
               and row["referred_columns"] == ["id"]
               and row["options"].get("ondelete") == "SET NULL" for row in foreign_keys):
        raise RuntimeError("Expected legacy Finance payment account reference is missing")

    for table in ("bank_account", "payment"):
        op.add_column(table, sa.Column("organization_id", sa.Integer(), nullable=True), schema="finance")
        op.create_foreign_key(
            op.f(f"fk_{table}_organization_id_organization"), table, "organization",
            ["organization_id"], ["id"], source_schema="finance", referent_schema="accounting",
            ondelete="RESTRICT",
        )
        op.create_index(op.f(f"ix_finance_{table}_organization_id"), table, ["organization_id"], schema="finance")
        op.create_check_constraint(
            op.f(f"ck_{table}_ck_finance_{table}_organization_positive"), table,
            "organization_id IS NULL OR organization_id > 0", schema="finance",
        )
    op.drop_constraint(op.f("uq_bank_account_code"), "bank_account", type_="unique", schema="finance")
    op.create_unique_constraint(op.f("uq_finance_bank_account_organization_code"), "bank_account", ["organization_id", "code"], schema="finance")
    op.create_unique_constraint(op.f("uq_finance_bank_account_organization_id"), "bank_account", ["organization_id", "id"], schema="finance")
    op.drop_constraint(op.f("fk_payment_account_id_bank_account"), "payment", type_="foreignkey", schema="finance")
    op.create_foreign_key(
        op.f("fk_payment_account_id_bank_account"), "payment", "bank_account", ["account_id"], ["id"],
        source_schema="finance", referent_schema="finance", ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_finance_payment_account_organization"), "payment", "bank_account",
        ["organization_id", "account_id"], ["organization_id", "id"],
        source_schema="finance", referent_schema="finance", ondelete="RESTRICT",
    )


def downgrade() -> None:
    bind = _locked_connection()
    owned = bind.execute(sa.text("""
        SELECT EXISTS (SELECT 1 FROM finance.payment WHERE organization_id IS NOT NULL)
            OR EXISTS (SELECT 1 FROM finance.bank_account WHERE organization_id IS NOT NULL)
    """)).scalar_one()
    if owned:
        raise RuntimeError("Confirmed Finance ownership cannot be discarded; use the verified release restore")
    duplicate_codes = bind.execute(sa.text("""
        SELECT EXISTS (SELECT 1 FROM finance.bank_account GROUP BY code HAVING count(*) > 1)
    """)).scalar_one()
    if duplicate_codes:
        raise RuntimeError("Duplicate legacy account codes prevent Finance rollback; use the verified release restore")

    op.drop_constraint(op.f("fk_finance_payment_account_organization"), "payment", type_="foreignkey", schema="finance")
    op.drop_constraint(op.f("fk_payment_account_id_bank_account"), "payment", type_="foreignkey", schema="finance")
    op.create_foreign_key(
        op.f("fk_payment_account_id_bank_account"), "payment", "bank_account", ["account_id"], ["id"],
        source_schema="finance", referent_schema="finance", ondelete="SET NULL",
    )
    op.drop_constraint(op.f("uq_finance_bank_account_organization_code"), "bank_account", type_="unique", schema="finance")
    op.drop_constraint(op.f("uq_finance_bank_account_organization_id"), "bank_account", type_="unique", schema="finance")
    op.create_unique_constraint(op.f("uq_bank_account_code"), "bank_account", ["code"], schema="finance")
    for table in ("payment", "bank_account"):
        op.drop_constraint(op.f(f"fk_{table}_organization_id_organization"), table, type_="foreignkey", schema="finance")
        op.drop_constraint(op.f(f"ck_{table}_ck_finance_{table}_organization_positive"), table, type_="check", schema="finance")
        op.drop_index(op.f(f"ix_finance_{table}_organization_id"), table_name=table, schema="finance")
        op.drop_column(table, "organization_id", schema="finance")
