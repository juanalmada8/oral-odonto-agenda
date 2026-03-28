"""Initial schema for odonto agenda ai."""

from alembic import op
import sqlalchemy as sa


revision = "20260326_01"
down_revision = None
branch_labels = None
depends_on = None


appointment_status = sa.Enum("reserved", "confirmed", "cancelled", "completed", name="appointment_status")
notification_channel = sa.Enum("email", "whatsapp", name="notification_channel")
notification_status = sa.Enum("pending", "sent", "failed", "skipped", name="notification_status")
notification_type = sa.Enum("confirmation", "reminder", "custom", name="notification_type")
user_role = sa.Enum("admin", "receptionist", name="user_role")


def upgrade() -> None:
    bind = op.get_bind()
    appointment_status.create(bind, checkfirst=True)
    notification_channel.create(bind, checkfirst=True)
    notification_status.create(bind, checkfirst=True)
    notification_type.create(bind, checkfirst=True)
    user_role.create(bind, checkfirst=True)

    op.create_table(
        "patient",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dni", sa.String(length=20), nullable=False, unique=True),
        sa.Column("first_name", sa.String(length=80), nullable=False),
        sa.Column("last_name", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_patient_id"), "patient", ["id"], unique=False)
    op.create_index(op.f("ix_patient_dni"), "patient", ["dni"], unique=True)

    op.create_table(
        "professional",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("first_name", sa.String(length=80), nullable=False),
        sa.Column("last_name", sa.String(length=80), nullable=False),
        sa.Column("specialty", sa.String(length=120), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True, unique=True),
        sa.Column("phone", sa.String(length=40), nullable=True, unique=True),
        sa.Column("default_appointment_duration", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_professional_id"), "professional", ["id"], unique=False)

    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=80), nullable=False, unique=True),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False, server_default="receptionist"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_user_id"), "user", ["id"], unique=False)
    op.create_index(op.f("ix_user_username"), "user", ["username"], unique=True)

    op.create_table(
        "working_hours",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("professional_id", sa.Integer(), sa.ForeignKey("professional.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("slot_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_working_hours_id"), "working_hours", ["id"], unique=False)

    op.create_table(
        "holiday_block",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("professional_id", sa.Integer(), sa.ForeignKey("professional.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_holiday_block_id"), "holiday_block", ["id"], unique=False)

    op.create_table(
        "appointment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patient.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("professional_id", sa.Integer(), sa.ForeignKey("professional.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("status", appointment_status, nullable=False, server_default="reserved"),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("created_by", sa.String(length=80), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_appointment_id"), "appointment", ["id"], unique=False)
    op.create_index(op.f("ix_appointment_patient_id"), "appointment", ["patient_id"], unique=False)
    op.create_index(op.f("ix_appointment_professional_id"), "appointment", ["professional_id"], unique=False)
    op.create_index(op.f("ix_appointment_starts_at"), "appointment", ["starts_at"], unique=False)

    op.create_table(
        "notification",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("appointment_id", sa.Integer(), sa.ForeignKey("appointment.id", ondelete="SET NULL"), nullable=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patient.id", ondelete="SET NULL"), nullable=True),
        sa.Column("type", notification_type, nullable=False),
        sa.Column("channel", notification_channel, nullable=False, server_default="email"),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=False), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("status", notification_status, nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_notification_id"), "notification", ["id"], unique=False)
    op.create_index(op.f("ix_notification_appointment_id"), "notification", ["appointment_id"], unique=False)
    op.create_index(op.f("ix_notification_patient_id"), "notification", ["patient_id"], unique=False)

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_name", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=80), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False, server_default="system"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_audit_log_id"), "audit_log", ["id"], unique=False)
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"], unique=False)
    op.create_index(op.f("ix_audit_log_entity_id"), "audit_log", ["entity_id"], unique=False)
    op.create_index(op.f("ix_audit_log_entity_name"), "audit_log", ["entity_name"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_log_entity_name"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_entity_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_id"), table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index(op.f("ix_notification_patient_id"), table_name="notification")
    op.drop_index(op.f("ix_notification_appointment_id"), table_name="notification")
    op.drop_index(op.f("ix_notification_id"), table_name="notification")
    op.drop_table("notification")

    op.drop_index(op.f("ix_appointment_starts_at"), table_name="appointment")
    op.drop_index(op.f("ix_appointment_professional_id"), table_name="appointment")
    op.drop_index(op.f("ix_appointment_patient_id"), table_name="appointment")
    op.drop_index(op.f("ix_appointment_id"), table_name="appointment")
    op.drop_table("appointment")

    op.drop_index(op.f("ix_holiday_block_id"), table_name="holiday_block")
    op.drop_table("holiday_block")

    op.drop_index(op.f("ix_working_hours_id"), table_name="working_hours")
    op.drop_table("working_hours")

    op.drop_index(op.f("ix_user_username"), table_name="user")
    op.drop_index(op.f("ix_user_id"), table_name="user")
    op.drop_table("user")

    op.drop_index(op.f("ix_professional_id"), table_name="professional")
    op.drop_table("professional")

    op.drop_index(op.f("ix_patient_id"), table_name="patient")
    op.drop_index(op.f("ix_patient_dni"), table_name="patient")
    op.drop_table("patient")

    bind = op.get_bind()
    notification_type.drop(bind, checkfirst=True)
    notification_status.drop(bind, checkfirst=True)
    notification_channel.drop(bind, checkfirst=True)
    user_role.drop(bind, checkfirst=True)
    appointment_status.drop(bind, checkfirst=True)
