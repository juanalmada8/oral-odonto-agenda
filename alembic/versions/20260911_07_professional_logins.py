"""Professional logins: link a user to the professional whose agenda they manage."""

import sqlalchemy as sa
from alembic import op


revision = "20260911_07"
down_revision = "20260911_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user") as batch_op:
        batch_op.add_column(sa.Column("professional_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_user_professional_id_professional", "professional", ["professional_id"], ["id"], ondelete="SET NULL"
        )
    op.create_index(op.f("ix_user_professional_id"), "user", ["professional_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_professional_id"), table_name="user")
    with op.batch_alter_table("user") as batch_op:
        batch_op.drop_constraint("fk_user_professional_id_professional", type_="foreignkey")
        batch_op.drop_column("professional_id")
