"""Persist immutable OSV reconciliation issue queues and unmatched rows."""
from alembic import op

revision = "0160"
down_revision = "0159"
branch_labels = None
depends_on = None


SQL = r"""
CREATE TABLE accounting.reconciliation_issue (
  id SERIAL PRIMARY KEY,
  organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
  request_key VARCHAR(36) NOT NULL,
  period_from DATE NOT NULL,
  period_to DATE NOT NULL,
  left_digest VARCHAR(64) NOT NULL,
  right_digest VARCHAR(64) NOT NULL,
  left_status VARCHAR(20) NOT NULL,
  right_status VARCHAR(20) NOT NULL,
  left_pending_documents INTEGER NOT NULL,
  right_pending_documents INTEGER NOT NULL,
  left_rows INTEGER NOT NULL,
  right_rows INTEGER NOT NULL,
  difference_count INTEGER NOT NULL,
  eligibility_blockers JSONB NOT NULL,
  responsible VARCHAR(200) NOT NULL,
  evidence VARCHAR(2000) NOT NULL,
  command_digest VARCHAR(64) NOT NULL,
  snapshot JSONB NOT NULL,
  digest VARCHAR(64) NOT NULL,
  actor VARCHAR(200) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_reconciliation_issue_request UNIQUE (organization_id, request_key),
  CONSTRAINT uq_reconciliation_issue_command UNIQUE (organization_id, command_digest),
  CONSTRAINT uq_reconciliation_issue_source_pair UNIQUE (organization_id, left_digest, right_digest),
  CONSTRAINT uq_reconciliation_issue_organization_id UNIQUE (organization_id, id),
  CONSTRAINT reconciliation_issue_difference_count CHECK (difference_count >= 0),
  CONSTRAINT reconciliation_issue_pending_documents CHECK (
    left_pending_documents >= 0 AND right_pending_documents >= 0
  ),
  CONSTRAINT reconciliation_issue_row_counts CHECK (left_rows >= 0 AND right_rows >= 0)
);
CREATE INDEX ix_reconciliation_issue_organization_id
  ON accounting.reconciliation_issue (organization_id, id DESC);

CREATE TABLE accounting.reconciliation_issue_item (
  id SERIAL PRIMARY KEY,
  organization_id INTEGER NOT NULL,
  issue_id INTEGER NOT NULL,
  item_key VARCHAR(64) NOT NULL,
  account VARCHAR(32) NOT NULL,
  dimensions JSONB NOT NULL,
  currency VARCHAR(3) NOT NULL,
  off_balance BOOLEAN NOT NULL,
  presence VARCHAR(12) NOT NULL,
  fields JSONB NOT NULL,
  digest VARCHAR(64) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_reconciliation_issue_item_organization FOREIGN KEY (organization_id, issue_id)
    REFERENCES accounting.reconciliation_issue (organization_id, id),
  CONSTRAINT uq_reconciliation_issue_item_key UNIQUE (organization_id, issue_id, item_key),
  CONSTRAINT uq_reconciliation_issue_item_organization_id UNIQUE (organization_id, issue_id, id),
  CONSTRAINT reconciliation_issue_item_presence CHECK (presence IN ('both', 'left_only', 'right_only'))
);
CREATE INDEX ix_reconciliation_issue_item_issue_id
  ON accounting.reconciliation_issue_item (organization_id, issue_id, id);

CREATE OR REPLACE FUNCTION accounting.guard_reconciliation_issue_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Reconciliation issue organization is unavailable';
  END IF;
  IF NEW.request_key !~ '^[0-9a-fA-F-]{36}$'
     OR NEW.period_from > NEW.period_to
     OR NEW.left_digest !~ '^[a-f0-9]{64}$'
     OR NEW.right_digest !~ '^[a-f0-9]{64}$'
     OR NEW.command_digest !~ '^[a-f0-9]{64}$'
     OR NEW.digest !~ '^[a-f0-9]{64}$'
     OR NEW.left_status NOT IN ('preliminary', 'closed_periods')
     OR NEW.right_status NOT IN ('preliminary', 'closed_periods')
     OR NEW.left_pending_documents < 0
     OR NEW.right_pending_documents < 0
     OR NEW.left_rows < 0
     OR NEW.right_rows < 0
     OR NEW.difference_count < 0
     OR jsonb_typeof(NEW.eligibility_blockers) <> 'array'
     OR jsonb_array_length(NEW.eligibility_blockers) = 0
     OR jsonb_typeof(NEW.snapshot) <> 'object'
     OR length(btrim(NEW.responsible)) = 0
     OR length(btrim(NEW.evidence)) < 10
     OR length(btrim(NEW.actor)) = 0 THEN
    RAISE EXCEPTION 'Reconciliation issue has incomplete immutable evidence';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements_text(NEW.eligibility_blockers) AS blocker(value)
    WHERE blocker.value NOT IN ('numeric_differences', 'reports_not_closed', 'pending_documents')
  ) THEN
    RAISE EXCEPTION 'Reconciliation issue has an unknown eligibility blocker';
  END IF;
  IF (NEW.difference_count > 0) <> (NEW.eligibility_blockers ? 'numeric_differences') THEN
    RAISE EXCEPTION 'Reconciliation issue difference count and blockers disagree';
  END IF;
  RETURN NEW;
END;
$$;
CREATE CONSTRAINT TRIGGER reconciliation_issue_insert_guard
AFTER INSERT ON accounting.reconciliation_issue
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.guard_reconciliation_issue_insert();

CREATE OR REPLACE FUNCTION accounting.guard_reconciliation_issue_item_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.item_key !~ '^[a-f0-9]{64}$'
     OR NEW.digest !~ '^[a-f0-9]{64}$'
     OR NEW.account !~ '^[0-9]+(\.[0-9]+)*$'
     OR NEW.currency !~ '^[A-Z]{3}$'
     OR NEW.presence NOT IN ('both', 'left_only', 'right_only')
     OR jsonb_typeof(NEW.dimensions) <> 'object'
     OR jsonb_typeof(NEW.fields) <> 'object' THEN
    RAISE EXCEPTION 'Reconciliation issue item is malformed';
  END IF;
  RETURN NEW;
END;
$$;
CREATE CONSTRAINT TRIGGER reconciliation_issue_item_insert_guard
AFTER INSERT ON accounting.reconciliation_issue_item
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.guard_reconciliation_issue_item_insert();

CREATE OR REPLACE FUNCTION accounting.guard_reconciliation_issue_item_count()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  issue_ref INTEGER;
  organization_ref INTEGER;
  expected_count INTEGER;
  actual_count INTEGER;
BEGIN
  IF TG_TABLE_NAME = 'reconciliation_issue' THEN
    issue_ref := NEW.id;
    organization_ref := NEW.organization_id;
  ELSE
    issue_ref := NEW.issue_id;
    organization_ref := NEW.organization_id;
  END IF;
  SELECT difference_count INTO expected_count
  FROM accounting.reconciliation_issue
  WHERE id = issue_ref AND organization_id = organization_ref;
  SELECT count(*) INTO actual_count
  FROM accounting.reconciliation_issue_item
  WHERE issue_id = issue_ref AND organization_id = organization_ref;
  IF expected_count IS NULL OR actual_count <> expected_count THEN
    RAISE EXCEPTION 'Reconciliation issue must retain every unmatched row';
  END IF;
  RETURN NEW;
END;
$$;
CREATE CONSTRAINT TRIGGER reconciliation_issue_count_after_issue
AFTER INSERT ON accounting.reconciliation_issue
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.guard_reconciliation_issue_item_count();
CREATE CONSTRAINT TRIGGER reconciliation_issue_count_after_item
AFTER INSERT ON accounting.reconciliation_issue_item
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.guard_reconciliation_issue_item_count();

CREATE OR REPLACE FUNCTION accounting.reject_reconciliation_issue_history_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Reconciliation issue history is immutable; compare fresh reports after correction';
END;
$$;
CREATE TRIGGER immutable_reconciliation_issue
BEFORE UPDATE OR DELETE ON accounting.reconciliation_issue
FOR EACH ROW EXECUTE FUNCTION accounting.reject_reconciliation_issue_history_mutation();
CREATE TRIGGER no_truncate_reconciliation_issue
BEFORE TRUNCATE ON accounting.reconciliation_issue
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_reconciliation_issue_history_mutation();
CREATE TRIGGER immutable_reconciliation_issue_item
BEFORE UPDATE OR DELETE ON accounting.reconciliation_issue_item
FOR EACH ROW EXECUTE FUNCTION accounting.reject_reconciliation_issue_history_mutation();
CREATE TRIGGER no_truncate_reconciliation_issue_item
BEFORE TRUNCATE ON accounting.reconciliation_issue_item
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_reconciliation_issue_history_mutation();
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.reconciliation_issue)
         OR EXISTS (SELECT 1 FROM accounting.reconciliation_issue_item) THEN
        RAISE EXCEPTION 'Cannot downgrade immutable reconciliation issue history';
      END IF;
    END $$;
    DROP TRIGGER no_truncate_reconciliation_issue_item ON accounting.reconciliation_issue_item;
    DROP TRIGGER immutable_reconciliation_issue_item ON accounting.reconciliation_issue_item;
    DROP TRIGGER no_truncate_reconciliation_issue ON accounting.reconciliation_issue;
    DROP TRIGGER immutable_reconciliation_issue ON accounting.reconciliation_issue;
    DROP FUNCTION accounting.reject_reconciliation_issue_history_mutation();
    DROP TRIGGER reconciliation_issue_count_after_item ON accounting.reconciliation_issue_item;
    DROP TRIGGER reconciliation_issue_count_after_issue ON accounting.reconciliation_issue;
    DROP FUNCTION accounting.guard_reconciliation_issue_item_count();
    DROP TRIGGER reconciliation_issue_item_insert_guard ON accounting.reconciliation_issue_item;
    DROP FUNCTION accounting.guard_reconciliation_issue_item_insert();
    DROP TRIGGER reconciliation_issue_insert_guard ON accounting.reconciliation_issue;
    DROP FUNCTION accounting.guard_reconciliation_issue_insert();
    DROP TABLE accounting.reconciliation_issue_item;
    DROP TABLE accounting.reconciliation_issue;
    """)
