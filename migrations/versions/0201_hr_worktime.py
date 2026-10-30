"""Persist explicit work sessions and reviewed daily timesheet results.

No employee, norm, presence or payroll records are synthesized by this migration.
"""
import sqlalchemy as sa
from alembic import op

revision = "0201"
down_revision = "0200"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "work_presence",
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr.employee.id"), primary_key=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        schema="hr",
    )
    op.create_table(
        "worktime_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr.employee.id"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("daily_minutes", sa.Integer(), nullable=False),
        sa.Column("weekmask", sa.Integer(), nullable=False),
        sa.Column("start_minute", sa.Integer()),
        sa.Column("manager_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("reference", sa.String(300), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("employee_id", "effective_from"),
        sa.CheckConstraint("daily_minutes > 0 AND daily_minutes <= 1440", name="worktime_norm"),
        sa.CheckConstraint("weekmask > 0 AND weekmask <= 127", name="worktime_weekmask"),
        sa.CheckConstraint("start_minute IS NULL OR (start_minute >= 0 AND start_minute < 1440)", name="worktime_start_minute"),
        schema="hr",
    )
    op.create_index("ix_hr_worktime_policy_employee_id", "worktime_policy", ["employee_id"], schema="hr")
    op.create_table(
        "work_session",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr.employee.id"), nullable=False),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("hr.worktime_policy.id"), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("start_key", sa.String(36), nullable=False),
        sa.Column("end_key", sa.String(36)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("employee_id", "work_date", name="uq_work_session_employee_date"),
        sa.UniqueConstraint("employee_id", "start_key", name="uq_work_session_employee_start_key"),
        sa.CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="work_session_time"),
        sa.CheckConstraint("last_seen_at >= started_at", name="work_session_presence"),
        sa.CheckConstraint("(ended_at IS NULL) = (end_key IS NULL)", name="work_session_end_key"),
        schema="hr",
    )
    op.create_index("ix_hr_work_session_employee_id", "work_session", ["employee_id"], schema="hr")
    op.create_index("uq_work_session_open_employee", "work_session", ["employee_id"], unique=True,
                    schema="hr", postgresql_where=sa.text("ended_at IS NULL"))
    op.create_table(
        "worktime_day",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr.employee.id"), nullable=False),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("hr.worktime_policy.id"), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("hr.work_session.id")),
        sa.Column("worked_seconds", sa.Integer(), nullable=False),
        sa.Column("norm_minutes", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(1)),
        sa.Column("absence_key", sa.String(36)),
        sa.Column("approval_id", sa.Integer(), sa.ForeignKey("approval.id"), unique=True),
        sa.Column("reference", sa.String(300), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("employee_id", "work_date"),
        sa.UniqueConstraint("absence_key"),
        sa.CheckConstraint("worked_seconds >= 0 AND worked_seconds <= 86400", name="worktime_seconds"),
        sa.CheckConstraint("norm_minutes >= 0 AND norm_minutes <= 1440", name="worktime_day_norm"),
        sa.CheckConstraint("code IS NULL OR code IN ('В', 'О', 'Б', 'К', 'А')", name="worktime_day_code"),
        sa.CheckConstraint("(session_id IS NOT NULL AND code IS NULL AND absence_key IS NULL) OR "
                           "(session_id IS NULL AND code IS NOT NULL AND absence_key IS NOT NULL AND worked_seconds = 0)",
                           name="worktime_day_source"),
        schema="hr",
    )
    op.create_index("ix_hr_worktime_day_employee_id", "worktime_day", ["employee_id"], schema="hr")
    op.create_table(
        "worktime_reminder",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr.employee.id"), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(5), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("hr.work_session.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("employee_id", "work_date", "kind", name="uq_worktime_reminder_employee_day_kind"),
        sa.CheckConstraint("kind IN ('start', 'end')", name="worktime_reminder_kind"), schema="hr",
    )
    op.create_index("ix_hr_worktime_reminder_employee_id", "worktime_reminder", ["employee_id"], schema="hr")
    op.execute("""
    CREATE FUNCTION hr.guard_worktime_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'Worktime policy and recorded day history are immutable';
    END $$;
    CREATE TRIGGER worktime_policy_immutable BEFORE UPDATE OR DELETE ON hr.worktime_policy
      FOR EACH ROW EXECUTE FUNCTION hr.guard_worktime_immutable();
    CREATE TRIGGER worktime_day_immutable BEFORE UPDATE OR DELETE ON hr.worktime_day
      FOR EACH ROW EXECUTE FUNCTION hr.guard_worktime_immutable();
    CREATE FUNCTION hr.guard_work_session() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Work session history cannot be deleted';
      END IF;
      IF OLD.ended_at IS NOT NULL THEN
        RAISE EXCEPTION 'Closed work session is immutable';
      END IF;
      IF (to_jsonb(NEW) - ARRAY['ended_at','end_key','last_seen_at']) IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['ended_at','end_key','last_seen_at'])
         OR NEW.last_seen_at < OLD.last_seen_at THEN
        RAISE EXCEPTION 'Work session identity and start are immutable';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER work_session_guard BEFORE UPDATE OR DELETE ON hr.work_session
      FOR EACH ROW EXECUTE FUNCTION hr.guard_work_session();
    """)


def downgrade():
    # An image/schema return must never silently erase recorded employee time.
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM hr.work_session) OR EXISTS (SELECT 1 FROM hr.worktime_day)
         OR EXISTS (SELECT 1 FROM hr.worktime_policy) THEN
        RAISE EXCEPTION 'Cannot downgrade recorded worktime or contract norms';
      END IF;
    END $$;
    """)
    op.drop_table("worktime_reminder", schema="hr")
    op.drop_table("worktime_day", schema="hr")
    op.drop_table("work_session", schema="hr")
    op.drop_table("worktime_policy", schema="hr")
    op.drop_table("work_presence", schema="hr")
    op.execute("DROP FUNCTION hr.guard_work_session(); DROP FUNCTION hr.guard_worktime_immutable();")
