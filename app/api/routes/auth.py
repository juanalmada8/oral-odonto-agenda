from fastapi import APIRouter, Depends, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_auth_service, get_current_user, require_roles
from app.core.enums import UserRole
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import TokenRead, UserCreate, UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenRead)
def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
):
    user = auth_service.authenticate(db, form_data.username, form_data.password)
    token = auth_service.create_token_for_user(user)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {token}",
        httponly=True,
        samesite="lax",
        max_age=auth_service.settings.access_token_expire_minutes * 60,
    )
    return TokenRead(access_token=token, user=user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie("access_token")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get(
    "/users",
    response_model=list[UserRead],
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def list_users(
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
):
    return auth_service.list_users(db)


@router.post(
    "/users",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(get_current_user),
):
    return auth_service.create_user(db, payload, actor=current_user.username)
