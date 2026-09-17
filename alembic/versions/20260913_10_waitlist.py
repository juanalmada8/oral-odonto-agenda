"""Waiting list: who wants an earlier slot than what is on offer.

When an appointment is cancelled or a hold expires, the freed slot is offered to the
first matching entry instead of sitting empty.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260913_10"
down_revision = "20260913_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "waitlist_entry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("professional_id", sa.Integer(), nullable=True),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("period", sa.String(length=20), nullable=False, server_default="any"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="waiting"),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("contact_phone", sa.String(length=40), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("notified_slot_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patient.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["professional_id"], ["professional.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_waitlist_entry_id"), "waitlist_entry", ["id"])
    op.create_index(op.f("ix_waitlist_entry_patient_id"), "waitlist_entry", ["patient_id"])
    op.create_index(op.f("ix_waitlist_entry_professional_id"), "waitlist_entry", ["professional_id"])
    op.create_index(op.f("ix_waitlist_entry_status"), "waitlist_entry", ["status"])


def downgrade() -> None:
    op.drop_table("waitlist_entry")
