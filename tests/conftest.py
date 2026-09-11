import os
from collections.abc import Generator
from datetime import datetime, timedelta

# Tests run against in-memory SQLite by default. Export TEST_DATABASE_URL (e.g. the CI PostgreSQL
# service) to run the same suite on PostgreSQL, with the schema built by the Alembic migrations.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or "sqlite+pysqlite:///:memory:"
# Never read the developer's .env: it may hold real SMTP, Mercado Pago or WhatsApp credentials.
os.environ["APP_ENV_FILE"] = ""
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["TEST_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["SECRET_KEY"] = "test-secret-key-32-chars-minimum!"
os.environ["APP_ENV"] = "test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core import clock  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.enums import UserRole  # noqa: E402
from app.core.rate_limit import rate_limiter  # noqa: E402
from app.db import models  # noqa: E402,F401
from app.db import session as db_session_module  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.auth import UserCreate  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402

settings = get_settings()
IS_SQLITE = settings.database_url.startswith("sqlite")

# Friday 2026-03-27 10:00 in the clinic timezone. Fixed so date-based rules are deterministic.
FROZEN_NOW = datetime(2026, 3, 27, 10, 0, 0)

if IS_SQLITE:
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
else:
    engine = create_engine(settings.database_url, future=True)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

# Code that opens its own sessions (background tasks, scheduled jobs) must hit the test database.
db_session_module.engine = engine
db_session_module.SessionLocal = TestingSessionLocal


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current

    def set(self, value: datetime) -> None:
        self.current = value

    def advance(self, **delta) -> None:
        self.current += timedelta(**delta)


@pytest.fixture(scope="session", autouse=True)
def database_schema() -> Generator[None, None, None]:
    if not IS_SQLITE:
        from alembic import command
        from alembic.config import Config

        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture(autouse=True)
def reset_database(database_schema) -> Generator[None, None, None]:
    if IS_SQLITE:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
    else:
        tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        with engine.begin() as connection:
            connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    rate_limiter.reset()
    yield


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch) -> FrozenClock:
    frozen = FrozenClock(FROZEN_NOW)
    monkeypatch.setattr(clock, "now", frozen.now)
    return frozen


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db():
        try:
            yield db_session
        except Exception:
            db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_user(db: Session, *, username: str, role: UserRole = UserRole.ADMIN, **extra):
    auth_service = AuthService(settings)
    return auth_service.create_user(
        db,
        UserCreate(
            username=username,
            full_name=f"{username.title()} Test",
            email=f"{username}@example.com",
            password="demo12345",
            role=role,
            **extra,
        ),
    )


def token_headers(user) -> dict[str, str]:
    token = AuthService(settings).create_token_for_user(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def auth_headers(db_session: Session) -> dict[str, str]:
    return token_headers(create_user(db_session, username="admin", role=UserRole.ADMIN))
