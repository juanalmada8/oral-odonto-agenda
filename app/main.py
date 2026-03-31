from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import DomainError
from app.core.logging import configure_logging
from app.db import models as _models  # noqa: F401  # Ensure all SQLAlchemy mappers are registered.
from app.web import router as web_router


settings = get_settings()
configure_logging(settings.debug)
BASE_DIR = Path(__file__).resolve().parent


app = FastAPI(
    title=settings.app_name,
    description=(
        "API para gestion de turnos de un consultorio odontologico. "
        "La logica esta separada por agentes internos de recepcion, agenda y seguimiento."
    ),
    version="0.1.0",
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    if request.url.path.startswith("/app") and exc.status_code == 401:
        return RedirectResponse(url="/app/login")
    if request.url.path.startswith("/app") and exc.status_code == 403:
        return RedirectResponse(url=f"/app?error={quote(exc.detail)}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/", tags=["health"])
def root():
    return RedirectResponse(url="/reservar")


@app.get("/health", tags=["health"])
def healthcheck() -> dict[str, str]:
    return {"status": "healthy"}


app.include_router(api_router, prefix=settings.api_prefix)
app.include_router(web_router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
