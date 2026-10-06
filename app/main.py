from pathlib import Path
from urllib.parse import quote

import logging
import mimetypes
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app import __version__
from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import DomainError
from app.core.logging import configure_logging, trace_context
from app.db import models as _models  # noqa: F401  # Ensure all SQLAlchemy mappers are registered.
from app.db import session as db_session
from app.web import router as web_router


settings = get_settings()
configure_logging(
    settings.debug,
    json_format=settings.log_format == "json",
    project_id=settings.google_cloud_project,
)
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent


app = FastAPI(
    title=settings.app_name,
    description=(
        "API para gestion de turnos de un consultorio odontologico. "
        "La logica esta separada en servicios de recepcion, agenda y seguimiento."
    ),
    version=__version__,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    trace_header = request.headers.get("x-cloud-trace-context")
    trace_context.set(trace_header.split("/", 1)[0] if trace_header else None)
    # Fresh per response: templates stamp it on their inline <script> tags and the CSP below only
    # runs scripts that carry it, so markup injected by an attacker cannot execute.
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'",
        )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if settings.is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith(("/app", "/reservar/turno", "/pagos")):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    # 303 and not the default 307: a rejected POST must land on a GET, otherwise the browser
    # replays the same POST against the redirect target.
    if request.url.path.startswith("/app") and exc.status_code == 401:
        return RedirectResponse(url="/app/login", status_code=303)
    if request.url.path.startswith("/app") and exc.status_code == 403:
        return RedirectResponse(url=f"/app?error={quote(exc.detail)}", status_code=303)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/", tags=["health"])
def root():
    return RedirectResponse(url="/reservar")


@app.get("/health", tags=["health"])
def healthcheck() -> dict[str, str]:
    """Liveness: the process answers."""
    return {"status": "healthy"}


@app.get("/health/ready", tags=["health"])
def readiness():
    """Readiness/startup probe: the database is reachable."""
    try:
        with db_session.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Readiness check failed")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready"}


app.include_router(api_router, prefix=settings.api_prefix)
app.include_router(web_router)

# La imagen de producción no trae la base de tipos del sistema, así que las fuentes
# salían como application/octet-stream. Se registran a mano para no depender del SO.
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
