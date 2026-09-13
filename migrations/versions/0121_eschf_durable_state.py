"""eschf: immutable artifacts, one attempt, durable status projection.

Reserved by scripts/next_migration.py for CRM-ESCHF-001-G04.
Local CP-only integration follows accepted CP G13 (0118).
Future SEND-first integration requires an explicit coordinated parent update.
"""

import sqlalchemy as sa
from alembic import op

revision = "0121"
down_revision = "0119"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA eschf")
    op.create_table(
        "original",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(24), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_original"),
        sa.UniqueConstraint(
            "source_document_id", "document_type", name="uq_original_source_document_id"
        ),
        schema="eschf",
    )
    op.create_table(
        "number_reservation",
        sa.Column("taxpayer_unp", sa.String(9), nullable=False),
        sa.Column("number", sa.String(30), nullable=False),
        sa.Column("original_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("taxpayer_unp", "number", name="pk_number_reservation"),
        sa.ForeignKeyConstraint(
            ["original_id"],
            ["eschf.original.id"],
            name="fk_number_reservation_original_id_original",
        ),
        sa.UniqueConstraint(
            "taxpayer_unp", "number", "original_id", name="uq_number_original_identity"
        ),
        schema="eschf",
    )
    op.create_table(
        "snapshot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("original_id", sa.Uuid(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid()),
        sa.Column("document_type", sa.String(24), nullable=False),
        sa.Column("source_document_id", sa.Integer(), nullable=False),
        sa.Column("source_document_version", sa.Integer(), nullable=False),
        sa.Column("source_content_sha256", sa.String(64), nullable=False),
        sa.Column("source_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("taxpayer_unp", sa.String(9), nullable=False),
        sa.Column("number", sa.String(30), nullable=False),
        sa.Column("binding_snapshot", sa.LargeBinary(), nullable=False),
        sa.Column("binding_sha256", sa.String(64), nullable=False),
        sa.Column("unsigned_xml", sa.LargeBinary(), nullable=False),
        sa.Column("unsigned_sha256", sa.String(64), nullable=False),
        sa.Column("adapter_id", sa.String(128), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_snapshot"),
        sa.UniqueConstraint("id", "unsigned_sha256", name="uq_snapshot_unsigned_identity"),
        sa.UniqueConstraint("id", "original_id", name="uq_snapshot_original_identity"),
        sa.UniqueConstraint("supersedes_id", name="uq_snapshot_supersedes_id"),
        sa.ForeignKeyConstraint(
            ["original_id"], ["eschf.original.id"], name="fk_snapshot_original_id_original"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["eschf.snapshot.id"], name="fk_snapshot_supersedes_id_snapshot"
        ),
        sa.ForeignKeyConstraint(
            ["taxpayer_unp", "number", "original_id"],
            [
                "eschf.number_reservation.taxpayer_unp",
                "eschf.number_reservation.number",
                "eschf.number_reservation.original_id",
            ],
            name="fk_snapshot_number_identity",
        ),
        sa.CheckConstraint("document_type = 'ORIGINAL'", name=op.f("ck_snapshot_original_only")),
        sa.CheckConstraint(
            "source_document_id > 0 AND source_document_version > 0",
            name=op.f("ck_snapshot_source"),
        ),
        sa.CheckConstraint(
            "environment IN ('synthetic', 'native')", name=op.f("ck_snapshot_environment")
        ),
        sa.CheckConstraint(
            "binding_sha256 = encode(sha256(binding_snapshot), 'hex') "
            "AND unsigned_sha256 = encode(sha256(unsigned_xml), 'hex')",
            name=op.f("ck_snapshot_artifact_hashes"),
        ),
        schema="eschf",
    )
    op.create_table(
        "delivery",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("approved_by", sa.String(128)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_binding_sha256", sa.String(64)),
        sa.Column("approved_unsigned_sha256", sa.String(64)),
        sa.Column("queued_at", sa.DateTime(timezone=True)),
        sa.Column("portal_since", sa.DateTime(timezone=True)),
        sa.Column("evidence_sha256", sa.String(64)),
        sa.Column("unknown_reason", sa.String(32)),
        sa.Column("observation_id", sa.Uuid()),
        sa.PrimaryKeyConstraint("snapshot_id", name="pk_delivery"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["eschf.snapshot.id"], name="fk_delivery_snapshot_id_snapshot"
        ),
        sa.CheckConstraint(
            "state IN ('prepared', 'approved', 'signed', 'queued', 'superseded', 'in_flight', "
            "'delivery_unknown', 'portal_processing', 'precheck_rejected', 'issued', "
            "'recipient_signed', 'agreement_pending', 'cancelled', 'cancellation_pending', "
            "'reconciliation_required', 'portal_error')",
            name=op.f("ck_delivery_state"),
        ),
        sa.CheckConstraint(
            "(state IN ('portal_processing', 'precheck_rejected', 'issued', 'recipient_signed', "
            "'agreement_pending', 'cancelled', 'cancellation_pending', 'reconciliation_required', "
            "'portal_error')) = (observation_id IS NOT NULL)",
            name=op.f("ck_delivery_portal_evidence"),
        ),
        schema="eschf",
    )
    op.create_table(
        "decision",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("binding_sha256", sa.String(64)),
        sa.Column("unsigned_sha256", sa.String(64)),
        sa.Column("reason", sa.String(32)),
        sa.PrimaryKeyConstraint("snapshot_id", "kind", name="pk_decision"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["eschf.snapshot.id"], name="fk_decision_snapshot_id_snapshot"
        ),
        sa.CheckConstraint(
            "kind IN ('approved', 'queued', 'unknown')", name=op.f("ck_decision_kind")
        ),
        sa.CheckConstraint(
            "(kind = 'approved' AND binding_sha256 IS NOT NULL AND unsigned_sha256 IS NOT NULL "
            "AND reason IS NULL) OR (kind = 'queued' AND binding_sha256 IS NULL AND "
            "unsigned_sha256 IS NULL AND reason IS NULL) OR (kind = 'unknown' AND "
            "binding_sha256 IS NULL AND unsigned_sha256 IS NULL AND reason IS NOT NULL AND reason IN "
            "('timeout', 'process_restart', 'lost_response', 'commit_unknown'))",
            name=op.f("ck_decision_payload"),
        ),
        schema="eschf",
    )
    op.create_table(
        "signed_artifact",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("signed_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("signed_sha256", sa.String(64), nullable=False),
        sa.Column("unsigned_sha256", sa.String(64), nullable=False),
        sa.Column("verification_evidence", sa.LargeBinary(), nullable=False),
        sa.Column("verification_sha256", sa.String(64), nullable=False),
        sa.Column("adapter_id", sa.String(128), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("snapshot_id", name="pk_signed_artifact"),
        sa.UniqueConstraint("snapshot_id", "signed_sha256", name="uq_signed_artifact_identity"),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "unsigned_sha256"],
            ["eschf.snapshot.id", "eschf.snapshot.unsigned_sha256"],
            name="fk_signed_artifact_unsigned_identity",
        ),
        sa.CheckConstraint(
            "signed_sha256 = encode(sha256(signed_bytes), 'hex') "
            "AND verification_sha256 = encode(sha256(verification_evidence), 'hex')",
            name=op.f("ck_signed_artifact_artifact_hashes"),
        ),
        schema="eschf",
    )
    op.create_table(
        "attempt",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("original_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("signed_sha256", sa.String(64), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("snapshot_id", name="pk_attempt"),
        sa.UniqueConstraint("claim_id", name="uq_attempt_claim_id"),
        sa.UniqueConstraint("original_id", name="uq_attempt_original_id"),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "original_id"],
            ["eschf.snapshot.id", "eschf.snapshot.original_id"],
            name="fk_attempt_original_identity",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "signed_sha256"],
            ["eschf.signed_artifact.snapshot_id", "eschf.signed_artifact.signed_sha256"],
            name="fk_attempt_signed_identity",
        ),
        schema="eschf",
    )
    op.create_table(
        "observation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("raw_evidence", sa.LargeBinary(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("adapter_id", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resulting_state", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_observation"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["eschf.attempt.snapshot_id"],
            name="fk_observation_snapshot_id_attempt",
        ),
        sa.UniqueConstraint("snapshot_id", "evidence_sha256", name="uq_observation_snapshot_id"),
        sa.UniqueConstraint("snapshot_id", "id", name="uq_observation_identity"),
        sa.CheckConstraint(
            "evidence_sha256 = encode(sha256(raw_evidence), 'hex')",
            name=op.f("ck_observation_artifact_hash"),
        ),
        schema="eschf",
    )
    op.create_foreign_key(
        "fk_delivery_observation_identity",
        "delivery",
        "observation",
        ["snapshot_id", "observation_id"],
        ["snapshot_id", "id"],
        source_schema="eschf",
        referent_schema="eschf",
    )
    op.execute("""
        CREATE FUNCTION eschf.guard_snapshot_revision() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent eschf.original%ROWTYPE; latest uuid;
        BEGIN
            SELECT * INTO STRICT parent FROM eschf.original WHERE id=NEW.original_id FOR UPDATE;
            IF (NEW.source_document_id, NEW.document_type, NEW.environment) IS DISTINCT FROM
               (parent.source_document_id, parent.document_type, parent.environment) THEN
                RAISE EXCEPTION 'ESCHF source identity mismatch' USING ERRCODE='23514';
            END IF;
            IF EXISTS (SELECT 1 FROM eschf.attempt WHERE original_id=parent.id) THEN
                RAISE EXCEPTION 'ESCHF attempted original cannot be refreshed' USING ERRCODE='23514';
            END IF;
            SELECT s.id INTO latest FROM eschf.snapshot s WHERE s.original_id=parent.id
                AND NOT EXISTS (SELECT 1 FROM eschf.snapshot n WHERE n.supersedes_id=s.id);
            IF NEW.supersedes_id IS DISTINCT FROM latest THEN
                RAISE EXCEPTION 'ESCHF refresh must supersede the current preview' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION eschf.guard_decision() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE preview eschf.snapshot%ROWTYPE;
        BEGIN
            SELECT * INTO STRICT preview FROM eschf.snapshot WHERE id=NEW.snapshot_id;
            PERFORM 1 FROM eschf.original WHERE id=preview.original_id FOR UPDATE;
            IF EXISTS (SELECT 1 FROM eschf.snapshot WHERE supersedes_id=preview.id) THEN
                RAISE EXCEPTION 'ESCHF superseded preview cannot advance' USING ERRCODE='23514';
            END IF;
            IF NEW.kind='approved' THEN
                IF (NEW.binding_sha256, NEW.unsigned_sha256) IS DISTINCT FROM
                   (preview.binding_sha256, preview.unsigned_sha256) OR
                   EXISTS (SELECT 1 FROM eschf.attempt WHERE original_id=preview.original_id) OR
                   EXISTS (SELECT 1 FROM eschf.signed_artifact WHERE snapshot_id=preview.id) THEN
                    RAISE EXCEPTION 'ESCHF invalid approval evidence' USING ERRCODE='23514';
                END IF;
            ELSIF NEW.kind='queued' THEN
                IF NOT EXISTS (SELECT 1 FROM eschf.signed_artifact WHERE snapshot_id=preview.id) OR
                   NOT EXISTS (SELECT 1 FROM eschf.decision WHERE snapshot_id=preview.id AND kind='approved') OR
                   EXISTS (SELECT 1 FROM eschf.attempt WHERE original_id=preview.original_id) THEN
                    RAISE EXCEPTION 'ESCHF queue requires unattempted approved signed bytes' USING ERRCODE='23514';
                END IF;
            ELSIF NEW.kind='unknown' THEN
                IF NOT EXISTS (SELECT 1 FROM eschf.attempt WHERE snapshot_id=preview.id) OR
                   EXISTS (SELECT 1 FROM eschf.observation WHERE snapshot_id=preview.id) THEN
                    RAISE EXCEPTION 'ESCHF unknown requires unresolved attempt' USING ERRCODE='23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION eschf.guard_signed_artifact() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE original_key uuid;
        BEGIN
            SELECT original_id INTO STRICT original_key FROM eschf.snapshot WHERE id=NEW.snapshot_id;
            PERFORM 1 FROM eschf.original WHERE id=original_key FOR UPDATE;
            IF EXISTS (SELECT 1 FROM eschf.snapshot WHERE supersedes_id=NEW.snapshot_id) OR
               EXISTS (SELECT 1 FROM eschf.attempt WHERE original_id=original_key) OR
               NOT EXISTS (SELECT 1 FROM eschf.decision WHERE snapshot_id=NEW.snapshot_id AND kind='approved') THEN
                RAISE EXCEPTION 'ESCHF signed artifact requires active approved preview' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION eschf.guard_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM 1 FROM eschf.original WHERE id=NEW.original_id FOR UPDATE;
            IF EXISTS (SELECT 1 FROM eschf.snapshot WHERE supersedes_id=NEW.snapshot_id) OR
               NOT EXISTS (SELECT 1 FROM eschf.decision WHERE snapshot_id=NEW.snapshot_id AND kind='queued') THEN
                RAISE EXCEPTION 'ESCHF attempt requires current queued preview' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    for table, function in (
        ("snapshot", "guard_snapshot_revision"),
        ("decision", "guard_decision"),
        ("signed_artifact", "guard_signed_artifact"),
        ("attempt", "guard_attempt"),
    ):
        op.execute(
            f"CREATE TRIGGER validate_insert BEFORE INSERT ON eschf.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION eschf.{function}()"
        )
    op.execute("""
        CREATE FUNCTION eschf.reject_artifact_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'ESCHF artifacts are immutable' USING ERRCODE = '23514';
        END $$
    """)
    for table in (
        "original",
        "number_reservation",
        "snapshot",
        "decision",
        "signed_artifact",
        "attempt",
        "observation",
    ):
        op.execute(f"""
            CREATE TRIGGER immutable_artifact BEFORE UPDATE OR DELETE ON eschf.{table}
            FOR EACH ROW EXECUTE FUNCTION eschf.reject_artifact_mutation()
        """)
        op.execute(f"""
            CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON eschf.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION eschf.reject_artifact_mutation()
        """)


def downgrade() -> None:
    for table in (
        "delivery",
        "observation",
        "attempt",
        "signed_artifact",
        "decision",
        "snapshot",
        "number_reservation",
        "original",
    ):
        op.drop_table(table, schema="eschf")
    for function in (
        "guard_attempt",
        "guard_signed_artifact",
        "guard_decision",
        "guard_snapshot_revision",
    ):
        op.execute(f"DROP FUNCTION eschf.{function}()")
    op.execute("DROP FUNCTION eschf.reject_artifact_mutation()")
    op.execute("DROP SCHEMA eschf")
