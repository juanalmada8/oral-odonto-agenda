"""One chair: the database rejects overlapping appointments across professionals (spec 0006, ADR 0010).

Replaces the per-professional exclusion constraint with one for the whole clinic. Same statuses as
before. If two active appointments of different professionals already overlap, the upgrade fails
(and, being a single transaction, changes nothing): resolve those first.
"""

from alembic import op

revision = "20261020_13"
down_revision = "20261006_12"
branch_labels = None
depends_on = None

# Frozen copy of the statuses that take the chair (app.core.enums.BLOCKING_APPOINTMENT_STATUSES).
BLOCKING_STATUSES = ("pending_payment", "reserved", "confirmed", "completed", "no_show")
PER_PROFESSIONAL = "appointment_professional_no_overlap"
WHOLE_CLINIC = "appointment_chair_no_overlap"


def _statuses() -> str:
    return ", ".join(f"'{status}'" for status in BLOCKING_STATUSES)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE appointment DROP CONSTRAINT IF EXISTS {PER_PROFESSIONAL}")
    op.execute(
        f"""
        ALTER TABLE appointment ADD CONSTRAINT {WHOLE_CLINIC}
        EXCLUDE USING gist (tsrange(starts_at, ends_at, '[)') WITH &&)
        WHERE (status IN ({_statuses()}))
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE appointment DROP CONSTRAINT IF EXISTS {WHOLE_CLINIC}")
    # int4range(id, id, '[]') lets GiST compare the professional with "=" without btree_gist.
    op.execute(
        f"""
        ALTER TABLE appointment ADD CONSTRAINT {PER_PROFESSIONAL}
        EXCLUDE USING gist (
            int4range(professional_id, professional_id, '[]') WITH =,
            tsrange(starts_at, ends_at, '[)') WITH &&
        ) WHERE (status IN ({_statuses()}))
        """
    )
