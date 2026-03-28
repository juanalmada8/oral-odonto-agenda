from fastapi import APIRouter

from app.api.routes import appointments, auth, availability, notifications, patients, professionals

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(patients.router)
api_router.include_router(professionals.router)
api_router.include_router(appointments.router)
api_router.include_router(availability.router)
api_router.include_router(notifications.router)
