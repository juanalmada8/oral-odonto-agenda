# Backups y restauración

La base tiene datos de pacientes y de pagos: el backup no es opcional.

## En producción (Cloud SQL)

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

- [ ] Los backups de los últimos 14 días existen.
- [ ] Se restauró una copia en una instancia de prueba y la app levantó contra ella.
- [ ] La instancia productiva tiene `deletion_protection` activo.
- [ ] Alguien más del equipo sabe ejecutar este procedimiento.
