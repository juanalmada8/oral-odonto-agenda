"""Notification outbox (retries, HTML, provider ids) and patient attendance confirmation."""

import sqlalchemy as sa
from alembic import op


revision = "20260911_06"
down_revision = "20260911_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("notification") as batch_op:
        batch_op.add_column(sa.Column("html_body", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("payload", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("last_attempt_at", sa.DateTime(timezone=False), nullable=True))
        batch_op.add_column(sa.Column("provider_message_id", sa.String(length=128), nullable=True))
    op.create_index(op.f("ix_notification_provider_message_id"), "notification", ["provider_message_id"], unique=False)
    op.create_index("ix_notification_status_scheduled_for", "notification", ["status", "scheduled_for"], unique=False)

    with op.batch_alter_table("appointment") as batch_op:
        batch_op.add_column(sa.Column("attendance_confirmed_at", sa.DateTime(timezone=False), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("appointment") as batch_op:
        batch_op.drop_column("attendance_confirmed_at")

    op.drop_index("ix_notification_status_scheduled_for", table_name="notification")
    op.drop_index(op.f("ix_notification_provider_message_id"), table_name="notification")
    with op.batch_alter_table("notification") as batch_op:
        batch_op.drop_column("provider_message_id")
        batch_op.drop_column("last_attempt_at")
        batch_op.drop_column("attempts")
        batch_op.drop_column("payload")
        batch_op.drop_column("html_body")
