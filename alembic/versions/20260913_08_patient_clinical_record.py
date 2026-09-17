"""Patient record fields the desk fills in on the first visit.

Online booking only asks for what a slot needs (name, DNI, contact). Everything else
is loaded by hand at the clinic, so every column is nullable.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260913_08"
down_revision = "20260911_07"
branch_labels = None
depends_on = None


def _columns() -> list[sa.Column]:
    """Built fresh on each call: a Column instance can only belong to one table."""
    return [
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("address", sa.String(length=180), nullable=True),
        sa.Column("city", sa.String(length=80), nullable=True),
        sa.Column("health_insurance", sa.String(length=120), nullable=True),
        sa.Column("health_insurance_number", sa.String(length=60), nullable=True),
        sa.Column("emergency_contact", sa.String(length=160), nullable=True),
        sa.Column("medical_notes", sa.Text(), nullable=True),
    ]


def upgrade() -> None:
    for column in _columns():
        op.add_column("patient", column)


def downgrade() -> None:
    for column in reversed(_columns()):
        op.drop_column("patient", column.name)
