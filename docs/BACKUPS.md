# Backups PostgreSQL (diario + retención)

## Objetivo recomendado para v1

- Backup diario automático.
- Retención mínima: 14 días.
- Al menos una restauración de prueba por mes.

## Opción A (recomendada): backup gestionado del proveedor

Si usás Render/Railway/Supabase/Neon, activá backups automáticos desde el panel.

Ventajas:

- Cero mantenimiento operativo.
- Restauración guiada.
- Menor riesgo de errores manuales.

## Opción B: script propio con `pg_dump`

El repo incluye:

- `ops/pg_backup.sh`

Ejemplo manual:

```bash
DATABASE_URL='postgresql://user:pass@host:5432/dbname' \
BACKUP_DIR='/var/backups/oral' \
RETENTION_DAYS=14 \
bash ops/pg_backup.sh
```

## Programación diaria con cron

Ejemplo: todos los días a las 03:00.

```cron
0 3 * * * DATABASE_URL='postgresql://user:pass@host:5432/dbname' BACKUP_DIR='/var/backups/oral' RETENTION_DAYS=14 /bin/bash /ruta/al/repo/ops/pg_backup.sh >> /var/log/oral_backup.log 2>&1
```

## Restauración (referencia)

```bash
pg_restore --clean --if-exists --no-owner --dbname='postgresql://user:pass@host:5432/dbname' /ruta/backup/oral_YYYYMMDD_HHMMSS.dump
```

## Checklist de backup para salida a producción

- backup diario activo
- retención 14+ días
- carpeta/volumen de backups fuera del contenedor principal
- restauración de prueba validada
