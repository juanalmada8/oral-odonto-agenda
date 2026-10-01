"""Drop the clinical notes column from the patient record.

Storing health data turns the database into one of "sensitive data" under Argentine law
25.326, with much heavier obligations. The product is a scheduling agenda, not a medical
record, so the field is removed: allergies and medication stay in the clinic's own history.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_11"
down_revision = "20260913_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("patient", "medical_notes")


def downgrade() -> None:
    op.add_column("patient", sa.Column("medical_notes", sa.Text(), nullable=True))
