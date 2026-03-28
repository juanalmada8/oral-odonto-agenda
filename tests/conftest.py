import os
from collections.abc import Generator

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["TEST_DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-32-chars-minimum!"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db import models  # noqa: F401
from app.db.session import get_db
from app.main import app
from app.schemas.auth import UserCreate
from app.services.auth_service import AuthService
from app.core.config import get_settings


SQLALCHEMY_DATABASE_URL = "sqlite+pysqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def reset_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


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
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(db_session: Session) -> dict[str, str]:
    auth_service = AuthService(get_settings())
    auth_service.create_user(
        db_session,
        UserCreate(
            username="admin",
            full_name="Admin Test",
            email="admin@example.com",
            password="demo12345",
        ),
    )
    token = auth_service.create_token_for_user(auth_service.get_user_by_username(db_session, "admin"))
    return {"Authorization": f"Bearer {token}"}
