from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_professional_service, require_roles
from app.core.enums import UserRole
from app.db.session import get_db
from app.models.user import User
from app.schemas.professional import ProfessionalCreate, ProfessionalRead, ProfessionalUpdate
from app.services.professional_service import ProfessionalService

router = APIRouter(
    prefix="/professionals",
    tags=["professionals"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST))],
)


@router.get("/", response_model=list[ProfessionalRead])
def list_professionals(
    db: Session = Depends(get_db),
    professional_service: ProfessionalService = Depends(get_professional_service),
):
    return professional_service.list_professionals(db)


@router.get("/{professional_id}", response_model=ProfessionalRead)
def get_professional(
    professional_id: int,
    db: Session = Depends(get_db),
    professional_service: ProfessionalService = Depends(get_professional_service),
):
    return professional_service.get_professional(db, professional_id)


@router.post("/", response_model=ProfessionalRead, status_code=status.HTTP_201_CREATED)
def create_professional(
    payload: ProfessionalCreate,
    db: Session = Depends(get_db),
    professional_service: ProfessionalService = Depends(get_professional_service),
    current_user: User = Depends(get_current_user),
):
    return professional_service.create_professional(db, payload, actor=current_user.username)


@router.put("/{professional_id}", response_model=ProfessionalRead)
def update_professional(
    professional_id: int,
    payload: ProfessionalUpdate,
    db: Session = Depends(get_db),
    professional_service: ProfessionalService = Depends(get_professional_service),
    current_user: User = Depends(get_current_user),
):
    return professional_service.update_professional(db, professional_id, payload, actor=current_user.username)


@router.delete("/{professional_id}", response_model=ProfessionalRead)
def delete_professional(
    professional_id: int,
    db: Session = Depends(get_db),
    professional_service: ProfessionalService = Depends(get_professional_service),
    current_user: User = Depends(get_current_user),
):
    return professional_service.deactivate_professional(db, professional_id, actor=current_user.username)
