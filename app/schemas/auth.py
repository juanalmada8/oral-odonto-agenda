from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.core.enums import UserRole
from app.schemas.common import TimestampedModel


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    full_name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole = UserRole.RECEPTIONIST
    professional_id: int | None = None

    @field_validator("username")
    @classmethod
    def lowercase_username(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def professional_link_matches_role(self):
        if self.role == UserRole.PROFESSIONAL and not self.professional_id:
            raise ValueError("Un usuario profesional tiene que estar vinculado a un profesional.")
        if self.role != UserRole.PROFESSIONAL:
            self.professional_id = None
        return self


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: EmailStr | None = None
    role: UserRole | None = None
    professional_id: int | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)


class UserRead(TimestampedModel):
    username: str
    full_name: str
    email: EmailStr
    role: UserRole
    professional_id: int | None
    is_active: bool


class TokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
