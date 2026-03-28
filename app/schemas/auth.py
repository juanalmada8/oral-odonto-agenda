from pydantic import BaseModel, EmailStr, Field

from app.core.enums import UserRole
from app.schemas.common import TimestampedModel


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=80)
    full_name: str = Field(..., max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole = UserRole.RECEPTIONIST


class UserRead(TimestampedModel):
    username: str
    full_name: str
    email: EmailStr
    role: UserRole
    is_active: bool


class TokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
