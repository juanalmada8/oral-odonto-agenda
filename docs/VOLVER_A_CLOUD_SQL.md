# Volver de Neon a Cloud SQL

Cuándo conviene hacerlo está en la [ADR 0011](decisions/0011-neon-postgres.md) (sección *Cuándo reabrir esta
decisión*). Es un cambio de configuración más una copia de datos: **no requiere tocar código**.
Contraparte de [MIGRACION_A_NEON.md](MIGRACION_A_NEON.md).

> ⚠ Los volcados contienen datos de pacientes: se guardan fuera del repositorio, en un disco cifrado, y se
> borran al terminar. Nada de esto se pega en chats ni commits.

## Qué camino seguir

| Situación | Camino |
| --- | --- |
| La instancia `oral-pg` **todavía existe** (estás dentro de los 14 días posteriores a la mudanza, o `keep_cloud_sql_instance` sigue en `true`) | **A · Vuelta rápida** |
| La instancia ya se eliminó | **B · Reconstruir Cloud SQL** |
| Neon está caído **ahora** y hay que atender ya | **A** si la instancia existe. Si Neon vuelve en poco, esperar suele ser mejor que mudar con datos nuevos sin copiar |

En los dos casos el último estado de los datos está en Neon (si responde) o, si no, en la última copia
diaria del bucket `gs://oral-odonto-agenda-oral-backups/` (se pierde lo cargado desde esa copia).

## Antes de empezar

```bash
brew install postgresql@16 cloud-sql-proxy
export PATH="$(brew --prefix postgresql@16)/bin:$PATH"
gcloud auth login && gcloud auth application-default login
```

### Paso común 1 · Tener los datos más recientes

Con Neon respondiendo, volcar directo:

```bash
pg_dump --format=custom --no-owner --no-privileges \
  -d "postgresql://oral_owner:CLAVE@HOST/oral?sslmode=require" -f ~/oral-vuelta.dump
pg_restore --list ~/oral-vuelta.dump | head          # lista tablas, sin errores
```

Con Neon caído, usar la última copia propia:

```bash
gcloud storage ls -l gs://oral-odonto-agenda-oral-backups/ | tail -3
gcloud storage cp gs://oral-odonto-agenda-oral-backups/oral_AAAAMMDD_HHMMSS.dump ~/oral-vuelta.dump
```

### Paso común 2 · Avisar y frenar las escrituras

Durante la copia (~20 minutos) el consultorio no debería cargar ni reservar turnos. Todo lo que se escriba
en Neon después del volcado se pierde al volver.

---

## A · Vuelta rápida (la instancia existe)

1. **Volcar Neon** (paso común 1).
2. **Volver a Cloud SQL en Terraform.** En `terraform.tfvars` quitá `database_backend = "neon"` (o poné
   `"cloud_sql"`) y:

   ```bash
   terraform plan
   ```

   Debe mostrar: se **crea** la versión de secreto de Cloud SQL (pasa a ser la "latest") y `run_sql_client`; se
   **destruyen** el job `oral-backup` y su schedule; el servicio y los jobs recuperan el volumen `/cloudsql`.
   **No debe tocar la instancia.** Con tu visto bueno, `terraform apply`.

   > Entre este apply y el paso 4 la app apunta a la base vieja, con datos desactualizados. Hacelo con el
   > consultorio fuera de línea.

3. **Cargar los datos más nuevos en Cloud SQL**, como dueño de las tablas (el usuario de la app). Con el
   proxy en otra terminal:

   ```bash
   cloud-sql-proxy --port 5433 oral-odonto-agenda:us-central1:oral-pg        # terminal 1

   # terminal 2: la contraseña sale del secreto, sin imprimirse
   export PGPASSWORD="$(gcloud secrets versions access latest --secret=oral-database-url \
     | python3 -c 'import sys,urllib.parse as u; print(u.urlparse(sys.stdin.read().strip()).password)')"
   pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error \
     -h 127.0.0.1 -p 5433 -U oral -d oral ~/oral-vuelta.dump
   unset PGPASSWORD
   ```

   (El usuario es `oral` porque el usuario de la app se llama como `service_name`.)

4. **Verificar** como en la fase 4 de la mudanza: filas por tabla iguales en Neon y Cloud SQL, mismo
   `alembic_version`, restricción de exclusión presente.
5. **Reiniciar la app contra la base**: `gcloud run jobs execute oral-migrate --region us-central1 --wait`
   y `curl -fsS https://oral.com.ar/health/ready`. Si el servicio no tomó la versión nueva del secreto,
   forzar una revisión: `gcloud run services update oral-web --region us-central1 --update-labels vuelta=$(date +%s)`.
6. **Reponer el acceso manual**, si usabas cuentas de Google: `ops/grant_db_access.sh <email>` por cada una
   (la restauración sin privilegios no los trae).
7. **Probar a mano** como en el paso 7 de la mudanza (reserva, panel, doble reserva, logs).
8. **Dejar Neon dormido** una semana más como respaldo y recién después borrar el proyecto desde su consola.
   Mientras tanto, la copia diaria **deja de correr** (su job se destruyó): Cloud SQL tiene sus copias
   nativas de 14 días. Si quisieras seguir con ellas: [BACKUPS.md](BACKUPS.md).
9. **Actualizar la documentación**: tabla *Esta instalación* de [DEPLOYMENT.md](DEPLOYMENT.md) y el estado de
   la ADR 0011 (*Reemplazada por…*, con la nueva).

## B · Reconstruir Cloud SQL (la instancia ya no existe)

1. **Volcar Neon** (paso común 1).
2. **Volver a Cloud SQL en Terraform:** `database_backend = "cloud_sql"` (y `db_deletion_protection = true`,
   que es el valor por defecto). `terraform plan` debe **crear** instancia, base, usuario, contraseña, la
   versión del secreto, los usuarios IAM y `run_sql_client`; y destruir el job de copias. Creala con tu visto
   bueno (`terraform apply`; tarda ~10 minutos).
3. **Restaurar en la base vacía** (el usuario de la app es el dueño y crea todo desde el volcado):

   ```bash
   cloud-sql-proxy --port 5433 oral-odonto-agenda:us-central1:oral-pg        # terminal 1
   export PGPASSWORD="$(gcloud secrets versions access latest --secret=oral-database-url \
     | python3 -c 'import sys,urllib.parse as u; print(u.urlparse(sys.stdin.read().strip()).password)')"
   pg_restore --no-owner --no-privileges --exit-on-error \
     -h 127.0.0.1 -p 5433 -U oral -d oral ~/oral-vuelta.dump                  # terminal 2
   unset PGPASSWORD
   ```

4. Seguir desde el paso 4 de la vuelta rápida (verificar, migrar, probar, accesos, documentación).

## Pasar a un plan de pago de Neon en vez de volver

Si el problema es el tope del plan gratuito o el historial corto y no Neon en sí, no hace falta mudar: se
sube de plan en su consola (cobro por uso, sin mínimo) y se puede ajustar el historial de restauración. La
aplicación no cambia. Si en cambio se quiere dejar de depender de la suspensión por inactividad, ese es el
momento de volver a Cloud SQL.

## Costo de volver

Cloud SQL `db-f1-micro` con disco de 10 GB, copias, IPv4 pública y registros de recuperación: del orden de
**USD 17-19 por mes** solo la base (estimado, a confirmar en la calculadora y en la facturación). Para
reducirlo un poco: copias de 7 en vez de 14, recuperación a un punto en el tiempo apagada y *Query Insights*
apagado; ver `infra/terraform/database.tf`.
