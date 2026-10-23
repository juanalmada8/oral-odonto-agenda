#!/bin/sh
set -eu

# Copia diaria de la base (Neon u otra) a un directorio de destino, normalmente el bucket montado en
# /backups por el job de Cloud Run. Es POSIX sh a propósito: corre en la imagen postgres:16-alpine.
#
# Obligatoria:  DATABASE_URL  (acepta el formato de SQLAlchemy, postgresql+psycopg://...)
# Opcionales:   BACKUP_DIR=/backups
#
# El volcado se hace primero en un directorio temporal y se comprueba que se pueda leer; recién entonces
# se copia al destino, con un nombre provisorio que se renombra al final. Así el bucket nunca contiene un
# archivo vacío, ilegible ni a medio escribir. La retención (30 días) la aplica el bucket, no este script.

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: falta DATABASE_URL." >&2
  exit 1
fi

BACKUP_DIR="${BACKUP_DIR:-/backups}"
STAMP="$(date -u +%Y%m%d_%H%M%S)"
NAME="oral_${STAMP}.dump"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

# pg_dump no entiende el sufijo del driver de SQLAlchemy (postgresql+psycopg://).
PG_URL="$(printf '%s' "$DATABASE_URL" | sed 's|^postgresql+[a-z0-9_]*://|postgresql://|')"

pg_dump --format=custom --no-owner --file="$WORK_DIR/$NAME" "$PG_URL"

if [ ! -s "$WORK_DIR/$NAME" ]; then
  echo "ERROR: el volcado quedó vacío; no se guarda." >&2
  exit 1
fi
if ! pg_restore --list "$WORK_DIR/$NAME" >/dev/null; then
  echo "ERROR: el volcado no se puede leer; no se guarda." >&2
  exit 1
fi

cp "$WORK_DIR/$NAME" "$BACKUP_DIR/$NAME.partial"
mv "$BACKUP_DIR/$NAME.partial" "$BACKUP_DIR/$NAME"

echo "Copia guardada: $BACKUP_DIR/$NAME ($(wc -c < "$BACKUP_DIR/$NAME") bytes)"
