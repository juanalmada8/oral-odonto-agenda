"""Add patient DNI column for existing local databases."""

from alembic import op
import sqlalchemy as sa


revision = "20260327_02"
down_revision = "20260326_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    patient_columns = {column["name"] for column in inspector.get_columns("patient")}
    patient_indexes = {index["name"] for index in inspector.get_indexes("patient")}

    if "dni" not in patient_columns:
        op.add_column("patient", sa.Column("dni", sa.String(length=20), nullable=True))
        op.execute(sa.text("UPDATE patient SET dni = CAST(99000000 + id AS TEXT) WHERE dni IS NULL"))

    if "ix_patient_dni" not in patient_indexes:
        op.create_index(op.f("ix_patient_dni"), "patient", ["dni"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    patient_columns = {column["name"] for column in inspector.get_columns("patient")}
    patient_indexes = {index["name"] for index in inspector.get_indexes("patient")}

    if "ix_patient_dni" in patient_indexes:
        op.drop_index(op.f("ix_patient_dni"), table_name="patient")

    if "dni" in patient_columns:
        with op.batch_alter_table("patient") as batch_op:
            batch_op.drop_column("dni")
