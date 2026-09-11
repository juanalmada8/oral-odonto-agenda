from enum import Enum as PyEnum

from sqlalchemy import Enum


def enum_column(enum_cls: type[PyEnum], *, length: int = 20) -> Enum:
    """Persist enum *values* ("confirmed") in a VARCHAR column.

    SQLAlchemy stores member *names* by default and native PostgreSQL enums need an
    ALTER TYPE for every new state; both broke production, so all enums use this type.
    """
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )
