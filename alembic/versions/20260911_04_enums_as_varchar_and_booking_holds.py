"""Store enums as VARCHAR values, add booking hold/contact columns and a race-safe slot constraint.

- PostgreSQL native enums were created with lowercase values while SQLAlchemy sent member names
  ("ADMIN"), so every insert failed on PostgreSQL. Columns become VARCHAR holding the values.
- SQLite databases stored member names; they are rewritten to the lowercase values.
- Appointments get an unguessable public token, booking contact data and a payment hold deadline.
- On PostgreSQL an exclusion constraint guarantees two active appointments of the same
  professional can never overlap, even under concurrent bookings.
"""

import secrets

import sqlalchemy as sa
from alembic import op


revision = "20260911_04"
down_revision = "20260327_03"
branch_labels = None
depends_on = None


ENUM_COLUMNS = [
    # table, column, legacy PostgreSQL enum type, server default
    ("appointment", "status", "appointment_status", "reserved"),
    ("notification", "type", "notification_type", None),
    ("notification", "channel", "notification_channel", "email"),
    ("notification", "status", "notification_status", "pending"),
    ("user", "role", "user_role", "receptionist"),
]

LEGACY_ENUM_VALUES = {
    "appointment_status": ("reserved", "confirmed", "cancelled", "completed"),
    "notification_type": ("confirmation", "reminder", "custom"),
    "notification_channel": ("email", "whatsapp"),
    "notification_status": ("pending", "sent", "failed", "skipped"),
    "user_role": ("admin", "receptionist"),
}

BLOCKING_STATUSES = ("pending_payment", "reserved", "confirmed", "completed", "no_show")
EXCLUSION_CONSTRAINT = "appointment_professional_no_overlap"


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    for table, column, _enum_type, default in ENUM_COLUMNS:
        if is_postgres:
            op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP DEFAULT')
            op.execute(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE VARCHAR(20) USING LOWER("{column}"::text)'
            )
            if default:
                op.execute(f"ALTER TABLE \"{table}\" ALTER COLUMN \"{column}\" SET DEFAULT '{default}'")
        else:
            op.execute(f'UPDATE "{table}" SET "{column}" = LOWER("{column}")')
    if is_postgres:
        for enum_type in LEGACY_ENUM_VALUES:
            op.execute(f"DROP TYPE IF EXISTS {enum_type}")

    with op.batch_alter_table("appointment") as batch_op:
        batch_op.add_column(sa.Column("public_token", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("contact_email", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("contact_phone", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("hold_expires_at", sa.DateTime(timezone=False), nullable=True))

    appointment = sa.table("appointment", sa.column("id", sa.Integer()), sa.column("public_token", sa.String()))
    for (appointment_id,) in bind.execute(sa.select(appointment.c.id)).all():
        bind.execute(
            appointment.update()
            .where(appointment.c.id == appointment_id)
            .values(public_token=secrets.token_urlsafe(24))
        )

    with op.batch_alter_table("appointment") as batch_op:
        batch_op.alter_column("public_token", existing_type=sa.String(length=64), nullable=False)
    op.create_index(op.f("ix_appointment_public_token"), "appointment", ["public_token"], unique=True)

    if is_postgres:
        # The initial schema enforced uniqueness twice (column UNIQUE constraint + unique index).
        op.execute("ALTER TABLE patient DROP CONSTRAINT IF EXISTS patient_dni_key")
        op.execute('ALTER TABLE "user" DROP CONSTRAINT IF EXISTS user_username_key')

        # int4range(id, id, '[]') lets GiST compare the professional with "=" without btree_gist,
        # so the constraint works on any PostgreSQL build.
        statuses = ", ".join(f"'{status}'" for status in BLOCKING_STATUSES)
        op.execute(
            f"""
            ALTER TABLE appointment ADD CONSTRAINT {EXCLUSION_CONSTRAINT}
            EXCLUDE USING gist (
                int4range(professional_id, professional_id, '[]') WITH =,
                tsrange(starts_at, ends_at, '[)') WITH &&
            ) WHERE (status IN ({statuses}))
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(f"ALTER TABLE appointment DROP CONSTRAINT IF EXISTS {EXCLUSION_CONSTRAINT}")
        op.execute("ALTER TABLE patient ADD CONSTRAINT patient_dni_key UNIQUE (dni)")
        op.execute('ALTER TABLE "user" ADD CONSTRAINT user_username_key UNIQUE (username)')

    op.drop_index(op.f("ix_appointment_public_token"), table_name="appointment")
    with op.batch_alter_table("appointment") as batch_op:
        batch_op.drop_column("hold_expires_at")
        batch_op.drop_column("contact_phone")
        batch_op.drop_column("contact_email")
        batch_op.drop_column("public_token")

    if is_postgres:
        # States introduced after the legacy enums cannot be represented; fold them into the closest one.
        op.execute("UPDATE appointment SET status = 'cancelled' WHERE status IN ('pending_payment', 'expired')")
        op.execute("UPDATE appointment SET status = 'completed' WHERE status = 'no_show'")
        op.execute("UPDATE notification SET type = 'custom' WHERE type NOT IN ('confirmation', 'reminder', 'custom')")
        op.execute("UPDATE \"user\" SET role = 'receptionist' WHERE role NOT IN ('admin', 'receptionist')")
        for enum_type, values in LEGACY_ENUM_VALUES.items():
            labels = ", ".join(f"'{value}'" for value in values)
            op.execute(f"CREATE TYPE {enum_type} AS ENUM ({labels})")
        for table, column, enum_type, default in ENUM_COLUMNS:
            op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP DEFAULT')
            op.execute(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE {enum_type} USING "{column}"::{enum_type}'
            )
            if default:
                op.execute(f"ALTER TABLE \"{table}\" ALTER COLUMN \"{column}\" SET DEFAULT '{default}'")
    else:
        for table, column, _enum_type, _default in ENUM_COLUMNS:
            op.execute(f'UPDATE "{table}" SET "{column}" = UPPER("{column}")')
