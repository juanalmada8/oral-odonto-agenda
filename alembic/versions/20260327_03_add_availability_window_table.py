"""Add availability windows for date-specific professional schedule."""

from alembic import op
import sqlalchemy as sa


revision = "20260327_03"
down_revision = "20260327_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "availability_window" not in tables:
        op.create_table(
            "availability_window",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("professional_id", sa.Integer(), nullable=False),
            sa.Column("availability_date", sa.Date(), nullable=False),
            sa.Column("start_time", sa.Time(), nullable=False),
            sa.Column("end_time", sa.Time(), nullable=False),
            sa.Column("slot_duration_minutes", sa.Integer(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["professional_id"], ["professional.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    window_indexes = {index["name"] for index in inspector.get_indexes("availability_window")} if "availability_window" in set(sa.inspect(bind).get_table_names()) else set()
    if "ix_availability_window_id" not in window_indexes:
        op.create_index(op.f("ix_availability_window_id"), "availability_window", ["id"], unique=False)
    if "ix_availability_window_availability_date" not in window_indexes:
        op.create_index(op.f("ix_availability_window_availability_date"), "availability_window", ["availability_date"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "availability_window" not in tables:
        return

    indexes = {index["name"] for index in inspector.get_indexes("availability_window")}
    if "ix_availability_window_availability_date" in indexes:
        op.drop_index(op.f("ix_availability_window_availability_date"), table_name="availability_window")
    if "ix_availability_window_id" in indexes:
        op.drop_index(op.f("ix_availability_window_id"), table_name="availability_window")
    op.drop_table("availability_window")
