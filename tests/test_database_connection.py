"""Spec 0010: la base remota va cifrada y ningún chequeo automático la despierta."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.db import session as db_session

NEON_URL = "postgresql://oral:secret@ep-quiet-sun-123456.us-east-2.aws.neon.tech/oral"
PRODUCTION = {"app_env": "production", "secret_key": "x" * 40, "public_base_url": "https://oral.example"}


def production_settings(database_url: str) -> Settings:
    return Settings(_env_file=None, database_url=database_url, **PRODUCTION)


def test_production_accepts_remote_database_with_ssl():
    for mode in ("require", "verify-ca", "verify-full"):
        production_settings(f"{NEON_URL}?sslmode={mode}")


@pytest.mark.parametrize("query", ["", "?sslmode=disable", "?sslmode=allow", "?sslmode=prefer", "?connect_timeout=15"])
def test_production_rejects_remote_database_without_ssl(query):
    with pytest.raises(ValidationError, match="sslmode"):
        production_settings(f"{NEON_URL}{query}")


def test_production_accepts_cloud_sql_socket():
    production_settings("postgresql+psycopg://oral:secret@/oral?host=/cloudsql/proyecto:us-central1:oral-pg")


def test_development_does_not_require_ssl():
    Settings(_env_file=None, database_url="postgresql://postgres:postgres@db:5432/odonto_agenda")


def test_liveness_never_touches_the_database(client, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("/health no debe abrir conexiones: despertaría a la base")

    monkeypatch.setattr(db_session.engine, "connect", boom)
    assert client.get("/health").json() == {"status": "healthy"}


def test_readiness_reports_unavailable_database(client, monkeypatch):
    def down(*args, **kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(db_session.engine, "connect", down)
    response = client.get("/health/ready")
    assert response.status_code == 503


def test_uptime_check_does_not_wake_the_database():
    monitoring = (Path(__file__).parent.parent / "infra/terraform/monitoring.tf").read_text()
    block = re.search(r'resource "google_monitoring_uptime_check_config" "web".*?\n}\n', monitoring, re.S)
    assert block, "no se encontró el chequeo de disponibilidad"
    path = re.search(r'path\s*=\s*"([^"]+)"', block.group(0))
    assert path and path.group(1) == "/health", "el monitor debe usar /health: /health/ready consulta la base"
