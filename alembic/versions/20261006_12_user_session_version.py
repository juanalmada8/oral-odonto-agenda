"""Add a session version to users, so a password change invalidates existing sessions.

Session tokens carry the version they were issued with; bumping it on a password change makes
every older token fail. Before this, a stolen session stayed valid until it expired (8 hours)
even after changing the password.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261006_12"
down_revision = "20261001_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("user", "session_version")
