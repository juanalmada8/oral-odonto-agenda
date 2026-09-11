from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


settings = get_settings()

if settings.database_url.startswith("sqlite"):
    engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        settings.database_url,
        future=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # Cloud SQL and serverless instances drop idle connections; test them before use.
        pool_pre_ping=True,
        pool_recycle=1800,
    )
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
