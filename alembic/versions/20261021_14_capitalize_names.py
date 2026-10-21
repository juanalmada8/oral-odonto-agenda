"""Capitalize patient and professional names already stored (spec 0007).

From now on the app capitalizes names when they are saved; this fixes the ones typed before
("juan martín" -> "Juan Martín", "ALMADA ORTIZ" -> "Almada Ortiz"). Words with intentional mixed
casing ("McDonald") are left alone. Data only: no schema change.

Downgrade is a no-op on purpose: the original casing is not kept, and restoring "juan martín" is
not something anyone wants.
"""

import re

import sqlalchemy as sa
from alembic import op

revision = "20261021_14"
down_revision = "20261020_13"
branch_labels = None
depends_on = None

# Frozen copy of app.utils.validation.capitalize_name (migrations must not import app code that changes).
NAME_PARTICLES = frozenset({"de", "del", "la", "las", "los", "y", "e", "van", "von"})
_NAME_SEPARATORS = re.compile(r"([ '\-.])")


def capitalize_name(value: str) -> str:
    result = []
    previous_separator = None
    first_word = True
    for piece in _NAME_SEPARATORS.split(value):
        if not piece:
            continue
        if _NAME_SEPARATORS.fullmatch(piece):
            result.append(piece)
            previous_separator = piece
            continue
        if piece.islower() or piece.isupper():
            lower = piece.lower()
            if not first_word and previous_separator == " " and lower in NAME_PARTICLES:
                piece = lower
            else:
                piece = lower[:1].upper() + lower[1:]
        result.append(piece)
        first_word = False
    return "".join(result)


def upgrade() -> None:
    bind = op.get_bind()
    for table in ("patient", "professional"):
        rows = bind.execute(sa.text(f"SELECT id, first_name, last_name FROM {table}")).all()
        for row_id, first_name, last_name in rows:
            fixed = (capitalize_name(first_name or ""), capitalize_name(last_name or ""))
            if fixed != (first_name, last_name):
                bind.execute(
                    sa.text(f"UPDATE {table} SET first_name = :first, last_name = :last WHERE id = :id"),
                    {"first": fixed[0], "last": fixed[1], "id": row_id},
                )


def downgrade() -> None:
    pass
