from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_reception_agent, require_roles
from app.core.enums import UserRole
from app.db.session import get_db
from app.models.user import User
from app.schemas.patient import PatientCreate, PatientRead, PatientUpdate
from app.services.reception_agent import ReceptionAgent

router = APIRouter(
    prefix="/patients",
    tags=["patients"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST))],
)


@router.get("/", response_model=list[PatientRead])
def list_patients(
    db: Session = Depends(get_db),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
):
    return reception_agent.list_patients(db)


@router.get("/{patient_id}", response_model=PatientRead)
def get_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
):
    return reception_agent.get_patient(db, patient_id)


@router.post("/", response_model=PatientRead, status_code=status.HTTP_201_CREATED)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
    current_user: User = Depends(get_current_user),
):
    return reception_agent.create_patient(db, payload, actor=current_user.username)


@router.put("/{patient_id}", response_model=PatientRead)
def update_patient(
    patient_id: int,
    payload: PatientUpdate,
    db: Session = Depends(get_db),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
    current_user: User = Depends(get_current_user),
):
    return reception_agent.update_patient(db, patient_id, payload, actor=current_user.username)


@router.delete("/{patient_id}", response_model=PatientRead)
def delete_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
    current_user: User = Depends(get_current_user),
):
    return reception_agent.deactivate_patient(db, patient_id, actor=current_user.username)
