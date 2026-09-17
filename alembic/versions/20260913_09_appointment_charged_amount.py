"""What the clinic actually charged for the visit.

The deposit is only part of the price, so revenue metrics that count deposits
alone under-report what came in.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260913_09"
down_revision = "20260913_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("appointment", sa.Column("charged_amount", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("appointment", "charged_amount")
