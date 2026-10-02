#!/usr/bin/env bash
# Crea un usuario administrador en producción (Cloud Run), sin datos de demostración.
#
#   ops/create_admin.sh <usuario> "<Nombre completo>" <email> [archivo-con-la-clave]
#
# Si no se pasa archivo, la clave se pide por teclado sin mostrarla. Así no queda en el historial
# de la terminal ni en ningún archivo. Es idempotente: si el usuario ya existe no se modifica.
#
# Cómo funciona: reutiliza el job de migraciones, que ya tiene acceso a la base. Lo apunta un
# momento a `app.tasks.create_admin`, lo ejecuta y lo restaura. La clave viaja por variable de
# entorno del job y se borra al terminar, incluso si algo falla o se interrumpe con Ctrl+C.
#
# Variables opcionales: GCP_PROJECT_ID, GCP_REGION (por defecto us-central1), MIGRATE_JOB
# (por defecto oral-migrate). Requiere gcloud autenticado con permiso sobre Cloud Run.
set -euo pipefail

if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
  sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
fi

USUARIO="$1"; NOMBRE="$2"; CORREO="$3"; ARCHIVO="${4:-}"
PROYECTO="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-us-central1}"
JOB="${MIGRATE_JOB:-oral-migrate}"

[ -n "$PROYECTO" ] || { echo "Definí GCP_PROJECT_ID o configurá un proyecto con gcloud." >&2; exit 2; }

if [ -n "$ARCHIVO" ]; then
  CLAVE="$(cat "$ARCHIVO")"
else
  read -r -s -p "Clave para '$USUARIO' (mínimo 8 caracteres): " CLAVE; echo
  read -r -s -p "Repetila: " REPETIDA; echo
  [ "$CLAVE" = "$REPETIDA" ] || { echo "Las claves no coinciden." >&2; exit 1; }
fi

# Las variables se pasan separadas por '|' para permitir comas en nombres y claves.
for valor in "$USUARIO" "$NOMBRE" "$CORREO" "$CLAVE"; do
  case "$valor" in *'|'*) echo "Ningún dato puede contener el carácter '|'." >&2; exit 2;; esac
done

COMUN=(--project "$PROYECTO" --region "$REGION" --quiet)

restaurar() {
  echo "→ restaurando el job y borrando las credenciales de su configuración"
  gcloud run jobs update "$JOB" "${COMUN[@]}" \
    --command alembic --args="upgrade,head" \
    --remove-env-vars ADMIN_USERNAME,ADMIN_FULL_NAME,ADMIN_EMAIL,ADMIN_PASSWORD >/dev/null
}
trap restaurar EXIT

echo "→ apuntando el job '$JOB' a create_admin"
gcloud run jobs update "$JOB" "${COMUN[@]}" \
  --command python --args="-m,app.tasks.create_admin" \
  --update-env-vars "^|^ADMIN_USERNAME=$USUARIO|ADMIN_FULL_NAME=$NOMBRE|ADMIN_EMAIL=$CORREO|ADMIN_PASSWORD=$CLAVE" >/dev/null

echo "→ ejecutando"
gcloud run jobs execute "$JOB" "${COMUN[@]}" --wait >/dev/null

echo "Listo: el administrador '$USUARIO' existe."
