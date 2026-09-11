"""Server-rendered pages and inbound webhooks."""

from fastapi import APIRouter

from app.web.admin import router as admin_router
from app.web.public import router as public_router
from app.web.webhooks import router as webhooks_router

router = APIRouter(include_in_schema=False)
router.include_router(public_router)
router.include_router(webhooks_router)
router.include_router(admin_router)
