#!/usr/bin/env bash
# Da acceso a las tablas de producción a una cuenta de Google ya declarada en `db_iam_users` (Terraform).
#
#   ops/grant_db_access.sh <email>
#
# Otorga lectura y escritura de datos (SELECT, INSERT, UPDATE, DELETE) sobre las tablas actuales y las que
# creen las migraciones futuras. NO otorga cambios de estructura (CREATE/ALTER/DROP): eso lo hacen solo las
# migraciones de Alembic, para que la base y el código no se desalineen.
#
# Corre dentro del job de tareas, que ya tiene la conexión de la app (dueña de las tablas). Es idempotente.
# Variables opcionales: GCP_PROJECT_ID, GCP_REGION (us-central1), SCHEDULED_JOB (oral-scheduled).
set -euo pipefail
[ "$#" -eq 1 ] || { sed -n '2,4p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
EMAIL="$1"
case "$EMAIL" in *'"'*|*"'"*|*'|'*|*' '*) echo "Email inválido." >&2; exit 2;; esac
PROYECTO="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-us-central1}"; JOB="${SCHEDULED_JOB:-oral-scheduled}"

CODIGO="from sqlalchemy import text; from app.db.session import engine
q = '\"$EMAIL\"'
sql = [
 f'GRANT USAGE ON SCHEMA public TO {q}',
 f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {q}',
 f'GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {q}',
 f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {q}',
 f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {q}',
]
with engine.begin() as c:
    [c.execute(text(s)) for s in sql]
    n = c.execute(text(\"SELECT count(DISTINCT table_name) FROM information_schema.role_table_grants WHERE grantee = :g\"), {'g': '$EMAIL'}).scalar()
print('ACCESO OTORGADO:', '$EMAIL', '- tablas con permiso:', n)"

echo "→ otorgando acceso a $EMAIL en $PROYECTO"
gcloud run jobs execute "$JOB" --project "$PROYECTO" --region "$REGION" --quiet --wait \
  --args="^|^-c|$CODIGO" >/dev/null
EJECUCION=$(gcloud run jobs executions list --job="$JOB" --project "$PROYECTO" --region "$REGION" --limit=1 --format="value(name)")
for _ in 1 2 3 4 5 6; do
  R=$(gcloud logging read "resource.type=cloud_run_job AND labels.\"run.googleapis.com/execution_name\"=\"$EJECUCION\" AND textPayload:\"ACCESO OTORGADO\"" \
      --project "$PROYECTO" --limit=1 --format="value(textPayload)" --freshness=15m 2>/dev/null)
  [ -n "$R" ] && { echo "$R"; exit 0; }; sleep 10
done
echo "No apareció la confirmación en los logs; revisá la ejecución $EJECUCION." >&2; exit 1
