#!/usr/bin/env bash
set -euo pipefail

# Backup PostgreSQL en formato custom (-Fc) con retención por días.
# Uso:
#   DATABASE_URL=postgresql://user:pass@host:5432/dbname bash ops/pg_backup.sh
# Variables opcionales:
#   BACKUP_DIR=./backups
#   RETENTION_DAYS=14

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TIMESTAMP="$(date +'%Y%m%d_%H%M%S')"

mkdir -p "$BACKUP_DIR"

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "ERROR: pg_dump no está instalado."
  exit 1
fi

if [[ -n "${DATABASE_URL:-}" ]]; then
  OUT_FILE="$BACKUP_DIR/oral_${TIMESTAMP}.dump"
  pg_dump --format=custom --file="$OUT_FILE" "$DATABASE_URL"
else
  DB_NAME="${POSTGRES_DB:-oral_db}"
  DB_USER="${POSTGRES_USER:-postgres}"
  DB_HOST="${POSTGRES_HOST:-localhost}"
  DB_PORT="${POSTGRES_PORT:-5432}"
  OUT_FILE="$BACKUP_DIR/oral_${DB_NAME}_${TIMESTAMP}.dump"
  pg_dump --format=custom --file="$OUT_FILE" --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" "$DB_NAME"
fi

find "$BACKUP_DIR" -type f -name "*.dump" -mtime +"$RETENTION_DAYS" -delete

echo "Backup generado: $OUT_FILE"
echo "Retención aplicada: ${RETENTION_DAYS} días"
