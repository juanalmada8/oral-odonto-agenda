"""Spec 0010: la copia diaria (ops/neon_backup.sh) nunca guarda un volcado vacío o ilegible."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "ops" / "neon_backup.sh"

FAKE_PG_DUMP = """#!/bin/sh
# Imita pg_dump: guarda cómo lo llamaron y escribe el contenido que pida el test.
for arg in "$@"; do
  case "$arg" in
    --file=*) out="${arg#--file=}" ;;
    postgresql*) printf '%s' "$arg" > "$FAKE_LOG" ;;
  esac
done
printf '%s' "$FAKE_DUMP_CONTENT" > "$out"
"""

FAKE_PG_RESTORE = """#!/bin/sh
# Imita pg_restore --list: solo acepta archivos con la firma de un volcado custom.
file="$2"
head -c 5 "$file" | grep -q PGDMP
"""


@pytest.fixture()
def tools(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("pg_dump", FAKE_PG_DUMP), ("pg_restore", FAKE_PG_RESTORE)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def run_backup(tmp_path, tools, *, database_url="postgresql+psycopg://u:p@host/oral?sslmode=require", dump="PGDMP-data"):
    destination = tmp_path / "bucket"
    destination.mkdir(exist_ok=True)
    env = {
        "PATH": f"{tools}{os.pathsep}/usr/bin:/bin",
        "BACKUP_DIR": str(destination),
        "TMPDIR": str(tmp_path),
        "FAKE_LOG": str(tmp_path / "pg_dump_url.txt"),
        "FAKE_DUMP_CONTENT": dump,
    }
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    result = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    return result, destination


def test_backup_stores_a_valid_dump(tmp_path, tools):
    result, destination = run_backup(tmp_path, tools)

    assert result.returncode == 0, result.stderr
    stored = sorted(p.name for p in destination.iterdir())
    assert len(stored) == 1
    assert stored[0].startswith("oral_") and stored[0].endswith(".dump")
    assert not [name for name in stored if name.endswith(".partial")]
    assert (destination / stored[0]).read_text() == "PGDMP-data"


def test_backup_translates_sqlalchemy_url(tmp_path, tools):
    result, _ = run_backup(tmp_path, tools, database_url="postgresql+psycopg://u:p@host/oral?sslmode=require")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "pg_dump_url.txt").read_text() == "postgresql://u:p@host/oral?sslmode=require"


@pytest.mark.parametrize("dump", ["", "esto no es un volcado"])
def test_backup_rejects_empty_or_unreadable_dump(tmp_path, tools, dump):
    result, destination = run_backup(tmp_path, tools, dump=dump)

    assert result.returncode != 0
    assert list(destination.iterdir()) == []


def test_backup_requires_database_url(tmp_path, tools):
    result, destination = run_backup(tmp_path, tools, database_url=None)

    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr
    assert list(destination.iterdir()) == []
