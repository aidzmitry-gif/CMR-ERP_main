"""Add immutable analytical receipts for already-posted expense lines."""

from alembic import op


revision = "0156"
down_revision = "0155"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE accounting.expense_article_attribution (
      id SERIAL NOT NULL,
      organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
      source_entry_id INTEGER NOT NULL REFERENCES accounting.entry(id),
      source_line_id INTEGER NOT NULL REFERENCES accounting.line(id),
      article_id INTEGER NOT NULL,
      supersedes_id INTEGER REFERENCES accounting.expense_article_attribution(id),
      request_key VARCHAR(36) NOT NULL,
      actor VARCHAR(200) NOT NULL,
      command_hash VARCHAR(64) NOT NULL,
      basis_digest VARCHAR(64) NOT NULL,
      effective_date DATE NOT NULL,
      evidence VARCHAR(1000) NOT NULL,
      explanation VARCHAR(1000) NOT NULL,
      source_snapshot JSON NOT NULL,
      article_snapshot JSON NOT NULL,
      receipt JSON NOT NULL,
      created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
      CONSTRAINT pk_expense_article_attribution PRIMARY KEY (id),
      CONSTRAINT uq_expense_article_attribution_request UNIQUE (organization_id, request_key),
      CONSTRAINT uq_expense_article_attribution_successor UNIQUE (supersedes_id),
      CONSTRAINT uq_expense_article_attribution_org_id UNIQUE (organization_id, id),
      CONSTRAINT fk_expense_article_attribution_article FOREIGN KEY (organization_id, article_id)
        REFERENCES accounting.expense_article(organization_id, id),
      CONSTRAINT ck_expense_article_attribution_positive_refs
        CHECK (source_entry_id > 0 AND source_line_id > 0 AND article_id > 0)
    );
    CREATE INDEX ix_expense_article_attribution_source_line
      ON accounting.expense_article_attribution(organization_id, source_line_id, id DESC);

    CREATE OR REPLACE FUNCTION accounting.guard_expense_article_attribution() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE
      source_entry accounting.entry%ROWTYPE;
      source_line accounting.line%ROWTYPE;
      predecessor accounting.expense_article_attribution%ROWTYPE;
      source_month text;
      receipt jsonb;
    BEGIN
      PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'Expense attribution organization is unavailable';
      END IF;
      SELECT * INTO source_entry FROM accounting.entry
        WHERE id=NEW.source_entry_id AND organization_id=NEW.organization_id;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'Expense attribution source entry is outside organization';
      END IF;
      SELECT * INTO source_line FROM accounting.line
        WHERE id=NEW.source_line_id AND entry_id=NEW.source_entry_id;
      IF NOT FOUND OR source_line.category<>'expense' OR source_line.currency<>'BYN' THEN
        RAISE EXCEPTION 'Expense attribution source line must be an BYN expense line';
      END IF;
      IF NEW.effective_date IS DISTINCT FROM source_entry.posting_date THEN
        RAISE EXCEPTION 'Expense attribution effective date must equal source posting date';
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM accounting.policy p
        WHERE p.id=source_entry.policy_id AND p.organization_id=NEW.organization_id
          AND p.effective_from<=source_entry.posting_date
      ) THEN
        RAISE EXCEPTION 'Expense attribution source policy is unavailable';
      END IF;
      source_month:=to_char(source_entry.posting_date, 'YYYY-MM');
      IF EXISTS (
        SELECT 1 FROM accounting.period
        WHERE organization_id=NEW.organization_id AND month=source_month AND closed
      ) THEN
        RAISE EXCEPTION 'Expense attribution source period is closed';
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM accounting.expense_article a
        JOIN accounting.expense_group g ON g.organization_id=a.organization_id AND g.id=a.group_id
        WHERE a.organization_id=NEW.organization_id AND a.id=NEW.article_id AND a.active AND g.active
      ) THEN
        RAISE EXCEPTION 'Expense attribution article is unavailable';
      END IF;
      IF coalesce(source_line.dimensions::jsonb->>'expense_article_id','') ~ '^[1-9][0-9]*$'
         AND EXISTS (
           SELECT 1 FROM accounting.expense_article direct_article
           WHERE direct_article.organization_id=NEW.organization_id
             AND direct_article.id=(source_line.dimensions::jsonb->>'expense_article_id')::integer
         ) THEN
        RAISE EXCEPTION 'Expense attribution source already has a direct article';
      END IF;
      IF NEW.supersedes_id IS NULL THEN
        IF EXISTS (
          SELECT 1 FROM accounting.expense_article_attribution
          WHERE organization_id=NEW.organization_id AND source_line_id=NEW.source_line_id
        ) THEN
          RAISE EXCEPTION 'Expense attribution chain must continue its latest receipt';
        END IF;
      ELSE
        SELECT * INTO predecessor FROM accounting.expense_article_attribution WHERE id=NEW.supersedes_id;
        IF NOT FOUND OR predecessor.organization_id<>NEW.organization_id
           OR predecessor.source_entry_id<>NEW.source_entry_id
           OR predecessor.source_line_id<>NEW.source_line_id THEN
          RAISE EXCEPTION 'Expense attribution successor does not match its predecessor';
        END IF;
      END IF;
      receipt:=NEW.receipt::jsonb;
      IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
         OR NEW.command_hash !~ '^[0-9a-f]{64}$'
         OR NEW.basis_digest !~ '^[0-9a-f]{64}$'
         OR length(btrim(NEW.actor))<1
         OR length(btrim(NEW.evidence)) NOT BETWEEN 1 AND 1000
         OR length(btrim(NEW.explanation)) NOT BETWEEN 1 AND 1000
         OR jsonb_typeof(receipt) IS DISTINCT FROM 'object'
         OR jsonb_typeof(receipt->'command') IS DISTINCT FROM 'object'
         OR jsonb_typeof(receipt->'result') IS DISTINCT FROM 'object'
         OR receipt->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
         OR receipt->>'principal' IS DISTINCT FROM NEW.actor
         OR receipt->>'kind' IS DISTINCT FROM 'expense_article_attribution'
         OR receipt->>'request_key' IS DISTINCT FROM NEW.request_key
         OR receipt->>'command_hash' IS DISTINCT FROM NEW.command_hash
         OR accounting.financial_sha(receipt->'command') IS DISTINCT FROM NEW.command_hash
         OR receipt#>>'{result,source_entry_id}' IS DISTINCT FROM NEW.source_entry_id::text
         OR receipt#>>'{result,source_line_id}' IS DISTINCT FROM NEW.source_line_id::text
         OR receipt#>>'{result,article_id}' IS DISTINCT FROM NEW.article_id::text
         OR receipt#>>'{result,effective_date}' IS DISTINCT FROM NEW.effective_date::text
         OR receipt#>>'{result,basis_digest}' IS DISTINCT FROM NEW.basis_digest
         OR receipt#>>'{result,evidence}' IS DISTINCT FROM NEW.evidence
         OR receipt#>>'{result,explanation}' IS DISTINCT FROM NEW.explanation
         OR receipt#>'{result,source_snapshot}' IS DISTINCT FROM NEW.source_snapshot::jsonb
         OR receipt#>'{result,article_snapshot}' IS DISTINCT FROM NEW.article_snapshot::jsonb
         OR accounting.financial_sha((receipt)-'receipt_digest') IS DISTINCT FROM receipt->>'receipt_digest'
         OR accounting.financial_sha(receipt->'result') IS DISTINCT FROM receipt->>'result_digest'
      THEN
        RAISE EXCEPTION 'Expense attribution receipt is inconsistent';
      END IF;
      IF NEW.supersedes_id IS NULL THEN
        IF receipt#>'{result,supersedes_id}' IS NOT NULL AND receipt#>'{result,supersedes_id}' <> 'null'::jsonb THEN
          RAISE EXCEPTION 'Expense attribution root receipt has an invalid predecessor';
        END IF;
      ELSIF receipt#>>'{result,supersedes_id}' IS DISTINCT FROM NEW.supersedes_id::text THEN
        RAISE EXCEPTION 'Expense attribution successor receipt has an invalid predecessor';
      END IF;
      RETURN NEW;
    END $$;

    CREATE TRIGGER guard_expense_article_attribution
      BEFORE INSERT ON accounting.expense_article_attribution
      FOR EACH ROW EXECUTE FUNCTION accounting.guard_expense_article_attribution();
    CREATE OR REPLACE FUNCTION accounting.reject_expense_article_attribution_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      RAISE EXCEPTION 'Expense article attributions are immutable';
    END $$;
    CREATE TRIGGER immutable_expense_article_attribution
      BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.expense_article_attribution
      FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_expense_article_attribution_mutation();
    """)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.expense_article_attribution) THEN
        RAISE EXCEPTION 'Cannot downgrade immutable expense article attribution history';
      END IF;
    END $$;
    DROP TABLE accounting.expense_article_attribution;
    DROP FUNCTION accounting.guard_expense_article_attribution();
    DROP FUNCTION accounting.reject_expense_article_attribution_mutation();
    """)
