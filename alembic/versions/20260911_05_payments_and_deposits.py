"""Deposits: payment table, per-professional deposit amount and appointment deposit snapshot."""

import sqlalchemy as sa
from alembic import op


revision = "20260911_05"
down_revision = "20260911_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("appointment_id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("preference_id", sa.String(length=128), nullable=True),
        sa.Column("checkout_url", sa.Text(), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=64), nullable=True),
        sa.Column("status_detail", sa.String(length=120), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointment.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payment_id"), "payment", ["id"], unique=False)
    op.create_index(op.f("ix_payment_appointment_id"), "payment", ["appointment_id"], unique=False)
    op.create_index(op.f("ix_payment_reference"), "payment", ["reference"], unique=True)
    op.create_index(op.f("ix_payment_preference_id"), "payment", ["preference_id"], unique=False)
    op.create_index(op.f("ix_payment_provider_payment_id"), "payment", ["provider_payment_id"], unique=True)

    with op.batch_alter_table("professional") as batch_op:
        batch_op.add_column(sa.Column("deposit_amount", sa.Numeric(12, 2), nullable=True))
    with op.batch_alter_table("appointment") as batch_op:
        batch_op.add_column(sa.Column("deposit_amount", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("appointment") as batch_op:
        batch_op.drop_column("deposit_amount")
    with op.batch_alter_table("professional") as batch_op:
        batch_op.drop_column("deposit_amount")

    op.drop_index(op.f("ix_payment_provider_payment_id"), table_name="payment")
    op.drop_index(op.f("ix_payment_preference_id"), table_name="payment")
    op.drop_index(op.f("ix_payment_reference"), table_name="payment")
    op.drop_index(op.f("ix_payment_appointment_id"), table_name="payment")
    op.drop_index(op.f("ix_payment_id"), table_name="payment")
    op.drop_table("payment")
