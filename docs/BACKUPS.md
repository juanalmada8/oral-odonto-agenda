# Backups y restauración

La base tiene datos de pacientes y de pagos: el backup no es opcional.

## En producción con Neon (`database_backend = "neon"`)

El plan gratuito de Neon solo conserva ~6 horas de historia, así que **la copia que cuenta es la propia**:

- **Copia diaria** a las 03:30 (hora de Buenos Aires): el job `oral-backup` hace `pg_dump`, valida que el
  volcado se pueda leer y recién entonces lo guarda en `gs://oral-odonto-agenda-oral-backups/` como
  `oral_AAAAMMDD_HHMMSS.dump`. Un volcado vacío o ilegible nunca llega al bucket (`ops/neon_backup.sh`).
- **Retención:** 30 días (`backup_retention_days`); el bucket borra solo lo más viejo. Es privado y de acceso
  uniforme.
- **Si falla**, llega un email a `alert_email` (alerta *falló la tarea programada o la copia de la base*).

Verificar que existen:

```bash
gcloud storage ls -l gs://oral-odonto-agenda-oral-backups/ | tail -5
gcloud run jobs execute oral-backup --region us-central1 --wait       # copia a pedido
```

### Restaurar una copia

Siempre sobre una base **nueva**, nunca encima de la que está en uso:

```bash
gcloud storage cp gs://oral-odonto-agenda-oral-backups/oral_AAAAMMDD_HHMMSS.dump ~/restaurar.dump
# En Neon: creá una base nueva (p. ej. oral_restaurada) o una rama, y restaurá ahí
pg_restore --no-owner --no-privileges --exit-on-error \
  -d "postgresql://oral_owner:CLAVE@HOST/oral_restaurada?sslmode=require" ~/restaurar.dump
```

Para volver a usarla en producción, cargá la URL de esa base como versión nueva de `oral-database-url` y
forzá una revisión del servicio (o restaurá sobre `oral` solo después de haber sacado una copia fresca).
Borrá `~/restaurar.dump` al terminar: tiene datos de pacientes.

**Neon también ofrece restauración de las últimas horas** (*Restore* en su consola): sirve para un error
reciente, pero no reemplaza a la copia propia.

## En producción con Cloud SQL (`database_backend = "cloud_sql"`)

Terraform deja configurado:

- **Backup diario automático** a las 06:00 UTC (03:00 en Buenos Aires), con 14 copias de retención.
- **Point-in-time recovery**: permite restaurar a cualquier momento de los últimos 7 días.

Verificar:

```bash
gcloud sql backups list --instance=oral-pg
```

### Restaurar

Sobre una **instancia nueva** (recomendado: no pisar la que está en uso):

```bash
# a partir de un backup
gcloud sql backups restore BACKUP_ID --restore-instance=oral-pg-restore --backup-instance=oral-pg

# a un momento exacto (PITR)
gcloud sql instances clone oral-pg oral-pg-restore \
  --point-in-time='2026-09-11T14:30:00Z'
```

Después apuntá `DATABASE_URL` a la instancia restaurada (o exportá y reimportá los datos) y verificá
la app antes de dar por cerrada la restauración.

### Copia fuera de Google (opcional pero sano)

```bash
gcloud sql export sql oral-pg gs://oral-turnos-backups/oral-$(date +%F).sql.gz \
  --database=oral --offload
```

Programalo con Cloud Scheduler si querés retención propia, y activá *Object Versioning* en el bucket.

## En desarrollo o en un servidor propio

El repo incluye `ops/pg_backup.sh` (`pg_dump` + retención):

```bash
DATABASE_URL='postgresql://user:pass@host:5432/db' BACKUP_DIR='/var/backups/oral' RETENTION_DAYS=14 \
  bash ops/pg_backup.sh
```

Restauración:

```bash
pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" /var/backups/oral/oral_YYYYMMDD_HHMMSS.dump
```

## Checklist trimestral

- [ ] Los backups de los últimos 14 días existen (en Neon: las copias diarias de los últimos 30 días).
- [ ] Se restauró una copia en una instancia de prueba y la app levantó contra ella.
- [ ] En Cloud SQL, la instancia productiva tiene `deletion_protection` activo. En Neon, la cuenta tiene verificación en dos pasos.
- [ ] Alguien más del equipo sabe ejecutar este procedimiento.
